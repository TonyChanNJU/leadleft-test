"""PDF upload router with persistence."""

import asyncio
import inspect
import logging
import os
import uuid
import json
import threading
from datetime import datetime
from typing import Any, Callable

import fitz
from fastapi import APIRouter, File, UploadFile, HTTPException, BackgroundTasks

from app.config import settings
from app.services.document_jobs import (
    complete_job,
    delete_job,
    ensure_document_job,
    ensure_job_store,
    fail_job,
    get_document_page_checkpoint_dir,
    job_lease_matches,
    list_recoverable_jobs,
    mark_job_recoverable,
    queue_job,
    reclaim_orphaned_running_jobs,
    reclaim_stale_running_jobs,
    renew_job_heartbeat,
    set_job_stage,
    start_job_attempt,
    touch_job_progress,
)
from app.services.pdf_parser import ParseProgress, parse_pdf
from app.services.indexer import IndexBuildProgress, build_index

logger = logging.getLogger(__name__)
router = APIRouter()

PROCESSING_QUEUED = "queued"
PROCESSING_PARSING = "parsing"
PROCESSING_OCR = "ocr"
PROCESSING_INDEXING = "indexing"
PROCESSING_READY = "ready"
PROCESSING_FAILED = "failed"


def _registry_file_path() -> str:
    """Compute current registry path from settings.

    Important for tests that monkeypatch `settings.upload_dir` to a temp folder.
    """
    return os.path.join(settings.upload_dir, "registry.json")


def load_registry() -> dict[str, dict]:
    """Load the document registry from disk."""
    registry_file = _registry_file_path()
    if os.path.exists(registry_file):
        try:
            with open(registry_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load registry: {e}")
    return {}


def save_registry(docs: dict[str, dict]):
    """Save the document registry to disk."""
    settings.ensure_dirs()
    try:
        with open(_registry_file_path(), "w") as f:
            json.dump(docs, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save registry: {e}")


_documents: dict[str, dict] = load_registry()
_active_pipeline_owners: dict[str, str] = {}
_active_pipeline_lock = threading.Lock()


def get_documents() -> dict[str, dict]:
    """Get the document registry."""
    return _documents


def _public_document_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """Return the client-facing subset of document metadata."""
    progress_percentage: int | None = None
    processing_status = meta.get(
        "processing_status",
        PROCESSING_READY if meta["indexed"] else PROCESSING_QUEUED,
    )

    if processing_status == PROCESSING_PARSING:
        total_pages = int(meta.get("total_pages") or 0)
        if total_pages > 0:
            progress_percentage = min(
                100,
                round((int(meta.get("processed_pages", 0)) / total_pages) * 100),
            )
    elif processing_status == PROCESSING_OCR:
        total_candidates = int(meta.get("ocr_candidate_pages_total") or 0)
        if total_candidates > 0:
            progress_percentage = min(
                100,
                round((int(meta.get("ocr_processed_pages", 0)) / total_candidates) * 100),
            )
    elif processing_status == PROCESSING_INDEXING:
        total_nodes = int(meta.get("index_total_nodes") or 0)
        if total_nodes > 0:
            progress_percentage = min(
                100,
                round((int(meta.get("index_done_nodes", 0)) / total_nodes) * 100),
            )
        else:
            total_batches = int(meta.get("index_total_batches") or 0)
            if total_batches > 0:
                progress_percentage = min(
                    100,
                    round((int(meta.get("index_done_batches", 0)) / total_batches) * 100),
                )

    return {
        "doc_id": meta["doc_id"],
        "filename": meta["filename"],
        "total_pages": meta.get("total_pages"),
        "uploaded_at": meta["uploaded_at"],
        "indexed": meta["indexed"],
        "processing_status": processing_status,
        "processing_message": meta.get("processing_message", ""),
        "processing_error": meta.get("processing_error"),
        "processed_pages": meta.get("processed_pages", 0),
        "processing_progress_pct": progress_percentage,
        "current_page": meta.get("current_page"),
        "ocr_pages": meta.get("ocr_pages", []),
        "ocr_candidate_pages_total": meta.get("ocr_candidate_pages_total", 0),
        "ocr_processed_pages": meta.get("ocr_processed_pages", 0),
        "index_total_nodes": meta.get("index_total_nodes", 0),
        "index_done_nodes": meta.get("index_done_nodes", 0),
        "index_total_batches": meta.get("index_total_batches", 0),
        "index_done_batches": meta.get("index_done_batches", 0),
        "low_quality_pages": meta.get("low_quality_pages", []),
        "ocr_provider": meta.get("ocr_provider", "none"),
    }


def _update_document_status(doc_id: str, **fields: Any) -> None:
    """Update one document status and persist the registry."""
    doc = _documents.get(doc_id)
    if doc is None:
        return
    doc.update(fields)
    save_registry(_documents)
    ensure_document_job(doc)
    touch_job_progress(
        doc_id,
        total_pages=doc.get("total_pages"),
        parsed_pages=doc.get("processed_pages", 0),
        ocr_candidate_pages_total=doc.get("ocr_candidate_pages_total", 0),
        ocr_processed_pages=doc.get("ocr_processed_pages", 0),
        index_total_nodes=doc.get("index_total_nodes", 0),
        index_done_nodes=doc.get("index_done_nodes", 0),
        index_total_batches=doc.get("index_total_batches", 0),
        index_done_batches=doc.get("index_done_batches", 0),
        current_page=doc.get("current_page"),
        current_batch=doc.get("current_batch"),
    )


def _validate_pdf_bytes(content: bytes) -> None:
    """Perform a cheap structural validation before queuing background work."""
    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to parse PDF: {str(exc)}") from exc
    doc.close()


def _reset_documents_for_tests() -> None:
    """Reset in-memory registry cache (used by tests only)."""
    global _documents
    _documents = load_registry()


def _new_lease_owner() -> str:
    """Create a unique lease owner token for one pipeline attempt."""
    return uuid.uuid4().hex


def bootstrap_document_jobs() -> None:
    """Ensure the persistent job store reflects the current registry."""
    ensure_job_store()
    for meta in _documents.values():
        ensure_document_job(meta)


def _status_message(stage: str, progress: ParseProgress | None = None) -> str:
    """Return a short human-friendly status message."""
    if stage == PROCESSING_QUEUED:
        return "Queued for processing."
    if stage == PROCESSING_PARSING:
        if progress and progress.total_pages:
            return (
                f"Parsing PDF structure ({progress.processed_pages}/{progress.total_pages} pages)."
            )
        return "Parsing PDF structure."
    if stage == PROCESSING_OCR:
        if progress and progress.total_pages:
            page_hint = progress.current_page or progress.processed_pages or 1
            return f"Running OCR fallback (page {page_hint}/{progress.total_pages})."
        return "Running OCR fallback."
    if stage == PROCESSING_INDEXING:
        if progress and progress.total_batches:
            return (
                "Building vector index "
                f"({progress.processed_nodes}/{progress.total_nodes} chunks, "
                f"batch {progress.processed_batches}/{progress.total_batches})."
            )
        return "Building vector index."
    if stage == PROCESSING_READY:
        return "Ready for queries."
    if stage == PROCESSING_FAILED:
        return "Processing failed."
    return "Processing."


def _is_current_pipeline_owner(doc_id: str, lease_owner: str) -> bool:
    """Return whether this process still considers the caller the active owner."""
    with _active_pipeline_lock:
        return _active_pipeline_owners.get(doc_id) == lease_owner


def _handle_parse_progress(doc_id: str, lease_owner: str, progress: ParseProgress) -> None:
    """Persist parser progress for frontend polling."""
    if not _is_current_pipeline_owner(doc_id, lease_owner):
        return
    renew_job_heartbeat(doc_id, lease_owner)
    if progress.stage in {PROCESSING_PARSING, PROCESSING_OCR}:
        set_job_stage(doc_id, progress.stage, lease_owner=lease_owner)
    _update_document_status(
        doc_id,
        processing_status=progress.stage,
        processing_message=_status_message(progress.stage, progress),
        processed_pages=progress.processed_pages,
        current_page=progress.current_page,
        total_pages=progress.total_pages,
        ocr_candidate_pages_total=progress.ocr_candidate_pages_total,
        ocr_processed_pages=progress.ocr_processed_pages,
    )


def _handle_index_progress(doc_id: str, lease_owner: str, progress: IndexBuildProgress) -> None:
    """Persist indexing progress for frontend polling."""
    if not _is_current_pipeline_owner(doc_id, lease_owner):
        return
    renew_job_heartbeat(doc_id, lease_owner)
    set_job_stage(doc_id, PROCESSING_INDEXING, lease_owner=lease_owner)
    _update_document_status(
        doc_id,
        processing_status=PROCESSING_INDEXING,
        processing_message=_status_message(PROCESSING_INDEXING, progress),
        index_total_nodes=progress.total_nodes,
        index_done_nodes=progress.processed_nodes,
        index_total_batches=progress.total_batches,
        index_done_batches=progress.processed_batches,
        current_batch=progress.processed_batches if progress.total_batches else None,
    )


def _run_document_pipeline(
    doc_id: str,
    file_path: str,
    original_filename: str,
    lease_owner: str,
) -> None:
    """Background task to parse the PDF and build its vector index."""
    try:
        start_job_attempt(doc_id, PROCESSING_PARSING, lease_owner)
        _update_document_status(
            doc_id,
            processing_status=PROCESSING_PARSING,
            processing_message=_status_message(PROCESSING_PARSING),
            processed_pages=0,
            current_page=None,
            processing_error=None,
        )
        parsed = parse_pdf(
            file_path,
            progress_callback=lambda progress: _handle_parse_progress(doc_id, lease_owner, progress),
            checkpoint_dir=get_document_page_checkpoint_dir(doc_id),
        )
        if not job_lease_matches(doc_id, lease_owner) or not _is_current_pipeline_owner(doc_id, lease_owner):
            logger.info("Lease changed while parsing %s; aborting stale attempt", doc_id)
            return
        parsed.filename = original_filename
        set_job_stage(doc_id, PROCESSING_INDEXING, lease_owner=lease_owner)
        existing_meta = _documents.get(doc_id, {})
        resume_done_batches = int(existing_meta.get("index_done_batches") or 0)
        resume_done_nodes = int(existing_meta.get("index_done_nodes") or 0)
        _update_document_status(
            doc_id,
            total_pages=parsed.total_pages,
            low_quality_pages=parsed.low_quality_pages,
            ocr_pages=parsed.ocr_pages,
            processing_status=PROCESSING_INDEXING,
            processing_message=_status_message(PROCESSING_INDEXING),
            processed_pages=parsed.total_pages,
            current_page=parsed.total_pages if parsed.total_pages else None,
            index_total_nodes=existing_meta.get("index_total_nodes", 0),
            index_done_nodes=resume_done_nodes,
            index_total_batches=existing_meta.get("index_total_batches", 0),
            index_done_batches=resume_done_batches,
            current_batch=None,
        )
        logger.info(
            "Building index in background for %s (%s pages)...",
            original_filename,
            parsed.total_pages,
        )
        build_index(
            doc_id,
            parsed,
            progress_callback=lambda progress: _handle_index_progress(doc_id, lease_owner, progress),
            resume_from_done_batches=resume_done_batches,
            resume_from_done_nodes=resume_done_nodes,
        )
        if not job_lease_matches(doc_id, lease_owner) or not _is_current_pipeline_owner(doc_id, lease_owner):
            logger.info("Lease changed while indexing %s; aborting stale completion", doc_id)
            return
        complete_job(doc_id)
        _update_document_status(
            doc_id,
            indexed=True,
            processing_status=PROCESSING_READY,
            processing_message=_status_message(PROCESSING_READY),
            processed_pages=parsed.total_pages,
            current_page=None,
            current_batch=None,
        )
        logger.info("Background index built successfully for %s", doc_id)
    except Exception as exc:
        logger.exception("Background indexing failed for %s", doc_id)
        if not job_lease_matches(doc_id, lease_owner) or not _is_current_pipeline_owner(doc_id, lease_owner):
            logger.info("Ignoring failure from stale attempt for %s: %s", doc_id, exc)
            return
        fail_job(doc_id, str(exc))
        _update_document_status(
            doc_id,
            indexed=False,
            processing_status=PROCESSING_FAILED,
            processing_message=_status_message(PROCESSING_FAILED),
            processing_error=str(exc),
            current_page=None,
            current_batch=None,
        )


def _reserve_document_pipeline(doc_id: str, lease_owner: str, *, replace: bool = False) -> bool:
    """Reserve one document pipeline slot in-process."""
    with _active_pipeline_lock:
        current_owner = _active_pipeline_owners.get(doc_id)
        if current_owner and current_owner != lease_owner and not replace:
            return False
        _active_pipeline_owners[doc_id] = lease_owner
        return True


def _release_document_pipeline(doc_id: str, lease_owner: str) -> None:
    """Release one in-process pipeline reservation."""
    with _active_pipeline_lock:
        if _active_pipeline_owners.get(doc_id) == lease_owner:
            _active_pipeline_owners.pop(doc_id, None)


def _run_document_pipeline_reserved(
    doc_id: str,
    file_path: str,
    original_filename: str,
    lease_owner: str,
) -> None:
    """Run the background pipeline for an already-reserved document."""
    try:
        if len(inspect.signature(_run_document_pipeline).parameters) >= 4:
            _run_document_pipeline(doc_id, file_path, original_filename, lease_owner)
        else:
            _run_document_pipeline(doc_id, file_path, original_filename)
    finally:
        _release_document_pipeline(doc_id, lease_owner)


def _run_document_pipeline_if_needed(doc_id: str, file_path: str, original_filename: str) -> None:
    """Run the background pipeline unless this process is already doing so."""
    lease_owner = _new_lease_owner()
    if not _reserve_document_pipeline(doc_id, lease_owner):
        logger.info("Skipping duplicate pipeline start for %s", doc_id)
        return
    _run_document_pipeline_reserved(doc_id, file_path, original_filename, lease_owner)


def _schedule_recovered_document_pipeline(doc_id: str, file_path: str, original_filename: str) -> bool:
    """Schedule one recovered document job onto the running event loop."""
    lease_owner = _new_lease_owner()
    if not _reserve_document_pipeline(doc_id, lease_owner, replace=True):
        return False
    asyncio.create_task(
        asyncio.to_thread(
            _run_document_pipeline_reserved,
            doc_id,
            file_path,
            original_filename,
            lease_owner,
        )
    )
    return True


def recover_pending_document_jobs(
    scheduler: Callable[[str, str, str], bool] | None = None,
) -> int:
    """Schedule unfinished jobs again after a backend restart."""
    bootstrap_document_jobs()
    schedule = scheduler or _schedule_recovered_document_pipeline
    recovered = 0
    for job in list_recoverable_jobs():
        doc_id = job["document_id"]
        meta = _documents.get(doc_id)
        if meta is None:
            delete_job(doc_id)
            continue

        file_path = meta.get("file_path") or job.get("file_path")
        if not file_path or not os.path.exists(file_path):
            fail_job(doc_id, "Original PDF file missing from disk")
            _update_document_status(
                doc_id,
                indexed=False,
                processing_status=PROCESSING_FAILED,
                processing_message=_status_message(PROCESSING_FAILED),
                processing_error="Original PDF file missing from disk",
                current_page=None,
            )
            continue

        queue_job(doc_id)
        _update_document_status(
            doc_id,
            indexed=False,
            processing_status=PROCESSING_QUEUED,
            processing_message=_status_message(PROCESSING_QUEUED),
            processing_error=None,
        )

        if not schedule(doc_id, file_path, meta["filename"]):
            continue
        recovered += 1
    return recovered


def recover_orphaned_document_jobs() -> int:
    """Recover jobs left running by a previous backend process."""
    reclaim_orphaned_running_jobs()
    return recover_pending_document_jobs()


def reclaim_and_recover_stale_document_jobs() -> int:
    """Reclaim stale leases and reschedule the newly recoverable jobs."""
    reclaimed = reclaim_stale_running_jobs(settings.job_lease_timeout_seconds)
    if not reclaimed:
        return 0

    recovered = 0
    for job in reclaimed:
        doc_id = job["document_id"]
        meta = _documents.get(doc_id)
        if meta is None:
            delete_job(doc_id)
            continue
        mark_job_recoverable(doc_id, "Lease expired during processing")
        _update_document_status(
            doc_id,
            indexed=False,
            processing_status=PROCESSING_QUEUED,
            processing_message=_status_message(PROCESSING_QUEUED),
            processing_error=None,
        )
        if _schedule_recovered_document_pipeline(doc_id, meta["file_path"], meta["filename"]):
            recovered += 1
    return recovered


@router.post("/upload")
async def upload_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Upload a PDF file, extract content, and build vector index.
    
    Returns document metadata including doc_id for subsequent queries.
    """
    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    if file.content_type and file.content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail="Invalid content type, expected application/pdf",
        )

    # Deduplicate: Check if filename already exists
    if any(doc.get("filename") == file.filename for doc in _documents.values()):
        raise HTTPException(
            status_code=409,
            detail=(
                "A document with this filename already exists. "
                "Please rename it or delete the existing one."
            ),
        )

    # Generate unique doc ID
    doc_id = str(uuid.uuid4())[:8]
    
    # Save file to disk
    settings.ensure_dirs()
    save_path = os.path.join(settings.upload_dir, f"{doc_id}_{file.filename}")

    try:
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        _validate_pdf_bytes(content)

        with open(save_path, "wb") as f:
            f.write(content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    # Register document
    doc_meta = {
        "doc_id": doc_id,
        "filename": file.filename,
        "file_path": save_path,
        "total_pages": None,
        "uploaded_at": datetime.now().isoformat(),
        "indexed": False,
        "processing_status": PROCESSING_QUEUED,
        "processing_message": _status_message(PROCESSING_QUEUED),
        "processing_error": None,
        "processed_pages": 0,
        "processing_progress_pct": None,
        "current_page": None,
        "ocr_candidate_pages_total": 0,
        "ocr_processed_pages": 0,
        "index_total_nodes": 0,
        "index_done_nodes": 0,
        "index_total_batches": 0,
        "index_done_batches": 0,
        "low_quality_pages": [],
        "ocr_pages": [],
        "ocr_provider": settings.ocr_provider,
    }
    _documents[doc_id] = doc_meta
    save_registry(_documents)
    ensure_document_job(doc_meta)

    # Parse + OCR + index in the background to keep the upload response snappy.
    background_tasks.add_task(_run_document_pipeline_if_needed, doc_id, save_path, file.filename)

    payload = _public_document_meta(doc_meta)
    payload["message"] = "PDF uploaded successfully. Processing in background."
    return payload
