"""PDF upload router with persistence."""

import logging
import os
import uuid
import json
from datetime import datetime

from fastapi import APIRouter, File, UploadFile, HTTPException, BackgroundTasks

from app.config import settings
from app.services.pdf_parser import parse_pdf
from app.services.indexer import build_index

logger = logging.getLogger(__name__)
router = APIRouter()

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


def _reset_documents_for_tests() -> None:
    """Reset in-memory registry cache (used by tests only)."""
    global _documents
    _documents = load_registry()


def _run_index_build(doc_id: str, file_path: str, original_filename: str) -> None:
    """Background task to build index and update registry."""
    try:
        parsed = parse_pdf(file_path)
        parsed.filename = original_filename
        logger.info("Building index in background for %s (%s pages)...", original_filename, parsed.total_pages)
        build_index(doc_id, parsed)
        _documents[doc_id]["indexed"] = True
        save_registry(_documents)
        logger.info("Background index built successfully for %s", doc_id)
    except Exception:
        logger.exception("Background indexing failed for %s", doc_id)
        # Keep indexed=false; registry already persisted.


@router.post("/upload")
async def upload_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Upload a PDF file, extract content, and build vector index.
    
    Returns document metadata including doc_id for subsequent queries.
    """
    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    if file.content_type and file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Invalid content type, expected application/pdf")

    # Deduplicate: Check if filename already exists
    if any(doc.get("filename") == file.filename for doc in _documents.values()):
        raise HTTPException(status_code=409, detail="A document with this filename already exists. Please rename it or delete the existing one.")

    # Generate unique doc ID
    doc_id = str(uuid.uuid4())[:8]
    
    # Save file to disk
    settings.ensure_dirs()
    save_path = os.path.join(settings.upload_dir, f"{doc_id}_{file.filename}")

    try:
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        with open(save_path, "wb") as f:
            f.write(content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    # Parse PDF
    try:
        parsed = parse_pdf(save_path)
        # Override the hash-prepended filename with original name for Indexing
        parsed.filename = file.filename
    except Exception as e:
        if os.path.exists(save_path):
            os.remove(save_path)
        raise HTTPException(status_code=422, detail=f"Failed to parse PDF: {str(e)}")

    # Register document first (index builds asynchronously).
    indexed = False

    # Register document
    doc_meta = {
        "doc_id": doc_id,
        "filename": file.filename,
        "file_path": save_path,
        "total_pages": parsed.total_pages,
        "uploaded_at": datetime.now().isoformat(),
        "indexed": indexed,
    }
    _documents[doc_id] = doc_meta
    save_registry(_documents)

    # Build index in the background to avoid blocking the upload request.
    background_tasks.add_task(_run_index_build, doc_id, save_path, file.filename)

    return {
        "doc_id": doc_id,
        "filename": file.filename,
        "total_pages": parsed.total_pages,
        "indexed": indexed,
        "message": f"PDF uploaded successfully. {parsed.total_pages} pages extracted. Indexing in background.",
    }
