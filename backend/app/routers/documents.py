"""Document management router."""

from fastapi import APIRouter, HTTPException

from app.routers.upload import get_documents

router = APIRouter()


@router.get("/documents")
async def list_documents():
    """List all uploaded documents."""
    docs = get_documents()
    return {
        "documents": [
            {
                "doc_id": meta["doc_id"],
                "filename": meta["filename"],
                "total_pages": meta["total_pages"],
                "uploaded_at": meta["uploaded_at"],
                "indexed": meta["indexed"],
            }
            for meta in docs.values()
        ]
    }


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str):
    """Get metadata for a specific document."""
    docs = get_documents()
    if doc_id not in docs:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    meta = docs[doc_id]
    return {
        "doc_id": meta["doc_id"],
        "filename": meta["filename"],
        "total_pages": meta["total_pages"],
        "uploaded_at": meta["uploaded_at"],
        "indexed": meta["indexed"],
    }

@router.get("/documents/{doc_id}/pdf")
async def get_document_pdf(doc_id: str):
    """Serve the raw PDF file for the given document via HTTP."""
    from fastapi.responses import FileResponse
    import os
    from urllib.parse import quote
    docs = get_documents()
    if doc_id not in docs:
        raise HTTPException(status_code=404, detail="Document not found in registry")
        
    meta = docs[doc_id]
    file_path = meta.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Original PDF file missing from disk")
        
    filename = meta.get("filename", f"{doc_id}.pdf")
    # Best-effort ASCII fallback for browsers that mishandle RFC 5987.
    ascii_fallback = "document.pdf"
    headers = {
        # Inline is required for iframe preview; RFC 5987 for UTF-8 filenames.
        "Content-Disposition": f'inline; filename="{ascii_fallback}"; filename*=UTF-8\'\'{quote(filename)}',
        # Prevent browsers from MIME-sniffing and accidentally treating PDF as text.
        "X-Content-Type-Options": "nosniff",
    }
    return FileResponse(
        path=file_path, 
        media_type="application/pdf",
        headers=headers,
    )


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    """Delete a document and its data."""
    import os
    docs = get_documents()
    if doc_id not in docs:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    meta = docs[doc_id]

    # Remove file from disk
    if os.path.exists(meta["file_path"]):
        os.remove(meta["file_path"])

    # Remove from registry
    del docs[doc_id]
    
    from app.routers.upload import save_registry
    save_registry(docs)

    # Remove from vector store
    from app.services.indexer import delete_index
    delete_index(doc_id)

    return {"message": f"Document {doc_id} deleted"}

@router.delete("/documents")
async def clear_all_documents():
    """Wipe all documents, registry, and vector datastore entirely."""
    import os
    import shutil
    from app.config import settings
    from app.routers.upload import get_documents, save_registry
    from app.services.indexer import reset_indexing_state
    
    # Reset in-process caches first to avoid stale handles during/after deletion.
    reset_indexing_state()

    docs = get_documents()
    docs.clear()
    save_registry(docs)
    
    # Wipe PDF uploads except registry
    if os.path.exists(settings.upload_dir):
        for f in os.listdir(settings.upload_dir):
            if f != "registry.json":
                try: 
                    os.remove(os.path.join(settings.upload_dir, f))
                except Exception: 
                    pass

    # Wipe Chroma
    if os.path.exists(settings.chroma_dir):
        shutil.rmtree(settings.chroma_dir, ignore_errors=True)
        os.makedirs(settings.chroma_dir, exist_ok=True)
        
    return {"message": "Registry and datastore completely wiped."}
