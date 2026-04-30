"""PDF upload router with persistence."""

import logging
import os
import uuid
import json
from datetime import datetime
from typing import Any

import fitz
from fastapi import APIRouter, File, UploadFile, HTTPException, BackgroundTasks

from app.config import settings
from app.services.pdf_parser import ParseProgress, parse_pdf
from app.services.indexer import build_index

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
        return "Building vector index."
    if stage == PROCESSING_READY:
        return "Ready for queries."
    if stage == PROCESSING_FAILED:
        return "Processing failed."
    return "Processing."


def _handle_parse_progress(doc_id: str, progress: ParseProgress) -> None:
    """Persist parser progress for frontend polling."""
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


def _run_document_pipeline(doc_id: str, file_path: str, original_filename: str) -> None:
    """Background task to parse the PDF and build its vector index."""
    try:
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
            progress_callback=lambda progress: _handle_parse_progress(doc_id, progress),
        )
        parsed.filename = original_filename
        _update_document_status(
            doc_id,
            total_pages=parsed.total_pages,
            low_quality_pages=parsed.low_quality_pages,
            ocr_pages=parsed.ocr_pages,
            processing_status=PROCESSING_INDEXING,
            processing_message=_status_message(PROCESSING_INDEXING),
            processed_pages=parsed.total_pages,
            current_page=parsed.total_pages if parsed.total_pages else None,
        )
        logger.info(
            "Building index in background for %s (%s pages)...",
            original_filename,
            parsed.total_pages,
        )
        build_index(doc_id, parsed)
        _update_document_status(
            doc_id,
            indexed=True,
            processing_status=PROCESSING_READY,
            processing_message=_status_message(PROCESSING_READY),
            processed_pages=parsed.total_pages,
            current_page=None,
        )
        logger.info("Background index built successfully for %s", doc_id)
    except Exception as exc:
        logger.exception("Background indexing failed for %s", doc_id)
        _update_document_status(
            doc_id,
            indexed=False,
            processing_status=PROCESSING_FAILED,
            processing_message=_status_message(PROCESSING_FAILED),
            processing_error=str(exc),
            current_page=None,
        )


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
        "low_quality_pages": [],
        "ocr_pages": [],
        "ocr_provider": settings.ocr_provider,
    }
    _documents[doc_id] = doc_meta
    save_registry(_documents)

    # Parse + OCR + index in the background to keep the upload response snappy.
    background_tasks.add_task(_run_document_pipeline, doc_id, save_path, file.filename)

    payload = _public_document_meta(doc_meta)
    payload["message"] = "PDF uploaded successfully. Processing in background."
    return payload
