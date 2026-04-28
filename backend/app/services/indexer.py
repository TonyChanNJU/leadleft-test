"""LlamaIndex indexing service.

Builds vector indexes from parsed PDF content using ChromaDB as the 
vector store and BGE-M3 embeddings.
"""

import os
from typing import Optional

import chromadb
from chromadb.errors import InternalError as ChromaInternalError
from llama_index.core import (
    Document,
    Settings,
    StorageContext,
    VectorStoreIndex,
)
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import TextNode
from llama_index.vector_stores.chroma import ChromaVectorStore

from app.config import settings as app_settings
from app.services.embedding import get_embedding_model
from app.services.pdf_parser import ParsedDocument


# Global instances
_chroma_client: Optional[chromadb.PersistentClient] = None
_embed_model = None


def reset_indexing_state() -> None:
    """Reset in-process caches (used after clearing chroma/upload dirs).

    ChromaDB's client and embedding instances are cached at module level.
    After a destructive wipe of the persistence directory, these objects can
    hold stale state and prevent subsequent indexing from working correctly.
    """
    global _chroma_client, _embed_model
    _chroma_client = None
    _embed_model = None

    # Also reset the embedding factory cache.
    try:
        from app.services.embedding import reset_embedding_cache

        reset_embedding_cache()
    except Exception:
        # Best-effort reset; indexing will recreate models as needed.
        pass


def _ensure_dir_writable(path: str) -> None:
    """Ensure persistence directory exists and is writable."""
    os.makedirs(path, exist_ok=True)
    test_path = os.path.join(path, ".write_test")
    try:
        with open(test_path, "w") as f:
            f.write("ok")
        os.remove(test_path)
    except Exception as e:
        raise RuntimeError(
            f"Chroma persistence dir is not writable: {path}. "
            f"Fix permissions or change the path. Underlying error: {e}"
        ) from e


def _get_chroma_client() -> chromadb.PersistentClient:
    """Get or create the ChromaDB persistent client."""
    global _chroma_client
    if _chroma_client is None:
        app_settings.ensure_dirs()
        _ensure_dir_writable(app_settings.chroma_dir)
        _chroma_client = chromadb.PersistentClient(
            path=app_settings.chroma_dir
        )
    return _chroma_client


def _get_embed_model():
    """Get or create the embedding model."""
    global _embed_model
    if _embed_model is None:
        _embed_model = get_embedding_model(
            provider=app_settings.embedding_provider,
            api_key=app_settings.siliconflow_api_key,
        )
    return _embed_model


def _collection_name(doc_id: str) -> str:
    """Generate a ChromaDB collection name for a document."""
    # ChromaDB collection names must be 3-63 chars, start/end with alphanumeric
    return f"doc_{doc_id}"


def build_index(doc_id: str, parsed_doc: ParsedDocument) -> VectorStoreIndex:
    """Build a vector index from a parsed PDF document.
    
    Creates LlamaIndex Documents with page metadata, chunks them,
    embeds with BGE-M3, and stores in ChromaDB.
    
    Args:
        doc_id: Unique document identifier.
        parsed_doc: Parsed PDF document from pdf_parser.
        
    Returns:
        VectorStoreIndex ready for querying.
    """
    # Create LlamaIndex documents with page metadata
    documents = []
    for page in parsed_doc.pages:
        content = page.full_content
        if not content.strip():
            continue
        doc = Document(
            text=content,
            metadata={
                "doc_id": doc_id,
                "page_num": page.page_num,
                "filename": parsed_doc.filename,
                "source": f"{parsed_doc.filename}, Page {page.page_num}",
            },
            excluded_llm_metadata_keys=["doc_id"],
            excluded_embed_metadata_keys=["doc_id"],
        )
        documents.append(doc)

    # Configure embedding model
    embed_model = _get_embed_model()
    Settings.embed_model = embed_model

    # Configure text splitter
    splitter = SentenceSplitter(
        chunk_size=app_settings.chunk_size,
        chunk_overlap=app_settings.chunk_overlap,
    )

    # Setup ChromaDB vector store
    chroma_client = _get_chroma_client()
    collection_name = _collection_name(doc_id)

    # Delete existing collection if re-indexing
    try:
        chroma_client.delete_collection(collection_name)
    except Exception:
        pass

    chroma_collection = chroma_client.get_or_create_collection(collection_name)
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    # Build nodes for pages (split) + tables (whole-block).
    #
    # Why: financial PDFs often put key facts (e.g. revenue) inside tables.
    # Sentence-based splitting can separate headers/row labels from numeric values,
    # making retrieval miss the right evidence. We therefore index tables as
    # whole markdown blocks with table-aware metadata.
    nodes = splitter.get_nodes_from_documents(documents)

    for page in parsed_doc.pages:
        for t in getattr(page, "tables", []) or []:
            md = (t.markdown or "").strip()
            if not md:
                continue
            nodes.append(
                TextNode(
                    text=md,
                    metadata={
                        "doc_id": doc_id,
                        "page_num": page.page_num,
                        "filename": parsed_doc.filename,
                        "source": f"{parsed_doc.filename}, Page {page.page_num}",
                        "content_type": "table",
                    },
                    excluded_llm_metadata_keys=["doc_id"],
                    excluded_embed_metadata_keys=["doc_id"],
                )
            )

    # Build index from nodes
    try:
        index = VectorStoreIndex(
            nodes=nodes,
            storage_context=storage_context,
            show_progress=True,
        )
    except ChromaInternalError as e:
        # Attempt one recovery for "readonly database" after a wipe/restart.
        msg = str(e).lower()
        if "readonly database" in msg or "read only database" in msg:
            reset_indexing_state()
            app_settings.ensure_dirs()
            _ensure_dir_writable(app_settings.chroma_dir)
            chroma_client = _get_chroma_client()
            chroma_collection = chroma_client.get_or_create_collection(collection_name)
            vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
            storage_context = StorageContext.from_defaults(vector_store=vector_store)
            index = VectorStoreIndex(
                nodes=nodes,
                storage_context=storage_context,
                show_progress=True,
            )
        else:
            raise

    return index


def load_index(doc_id: str) -> Optional[VectorStoreIndex]:
    """Load an existing vector index from ChromaDB.
    
    Args:
        doc_id: Document identifier.
        
    Returns:
        VectorStoreIndex if the collection exists, None otherwise.
    """
    chroma_client = _get_chroma_client()
    collection_name = _collection_name(doc_id)

    try:
        chroma_collection = chroma_client.get_collection(collection_name)
    except Exception:
        return None

    if chroma_collection.count() == 0:
        return None

    # Configure embedding model
    embed_model = _get_embed_model()
    Settings.embed_model = embed_model

    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    index = VectorStoreIndex.from_vector_store(vector_store)

    return index


def delete_index(doc_id: str) -> bool:
    """Delete a document's vector index from ChromaDB.
    
    Args:
        doc_id: Document identifier.
        
    Returns:
        True if deleted, False if not found.
    """
    chroma_client = _get_chroma_client()
    collection_name = _collection_name(doc_id)

    try:
        chroma_client.delete_collection(collection_name)
        return True
    except Exception:
        return False


def list_indexed_docs() -> list[str]:
    """List all document IDs that have been indexed."""
    chroma_client = _get_chroma_client()
    collections = chroma_client.list_collections()
    doc_ids = []
    for col in collections:
        name = col if isinstance(col, str) else col.name
        if name.startswith("doc_"):
            doc_ids.append(name[4:])  # Remove "doc_" prefix
    return doc_ids
