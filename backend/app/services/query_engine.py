"""Query engine service with citation support.

Uses LlamaIndex to retrieve relevant chunks from ChromaDB and
generate answers with source citations (page numbers + text snippets).
"""

import logging
from typing import Optional

from llama_index.core import Settings, VectorStoreIndex
from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.postprocessor import SimilarityPostprocessor

from app.config import settings as app_settings
from app.services.embedding import get_embedding_model
from app.services.indexer import load_index
from app.services.llm_provider import create_llm

logger = logging.getLogger(__name__)

# System prompt for document QA
SYSTEM_PROMPT = """You are a document Q&A assistant. Your job is to answer questions based ONLY on the provided document content.

Rules:
1. ONLY answer based on the provided context from the document. Do NOT use your own prior knowledge.
2. If the document does not contain enough information to answer the question, say so honestly. Do NOT guess or make up information.
3. Always cite your sources by mentioning the page number(s) where the information was found.
4. When possible, include a brief direct quote from the document to support your answer.
5. For numerical questions, provide exact numbers from the document.
6. For summary questions, be comprehensive but concise.
7. Respond in the same language as the user's question (Chinese or English).

Format your citations like this: (Source: filename, Page X)
"""


def _format_context(nodes) -> str:
    """Format retrieved nodes into a context string for the LLM."""
    from app.routers.upload import get_documents

    docs = get_documents()
    context_parts = []
    for i, node in enumerate(nodes, 1):
        metadata = node.metadata or {}
        page_num = metadata.get("page_num", "?")
        doc_id = metadata.get("doc_id", "")
        filename = (docs.get(doc_id) or {}).get("filename") or metadata.get("filename", "unknown")
        score = getattr(node, "score", None)
        score_str = f" [relevance: {score:.3f}]" if score else ""

        context_parts.append(
            f"[Source {i}: {filename}, Page {page_num}{score_str}]\n{node.text}\n"
        )

    return "\n---\n".join(context_parts)


def _extract_citations(nodes) -> list[dict]:
    """Extract citation information from retrieved nodes."""
    from app.routers.upload import get_documents

    docs = get_documents()
    citations = []
    seen = set()

    for node in nodes:
        metadata = node.metadata or {}
        page_num = metadata.get("page_num", 0)
        doc_id = metadata.get("doc_id", "")
        filename = (docs.get(doc_id) or {}).get("filename") or metadata.get("filename", "")

        # Deduplicate by page and document
        key = (doc_id, page_num)
        if key in seen:
            continue
        seen.add(key)

        # Get a snippet (first 200 chars of the chunk)
        text_snippet = node.text[:200].strip()
        if len(node.text) > 200:
            text_snippet += "..."

        citations.append({
            "page_num": page_num,
            "text": text_snippet,
            "filename": filename,
            "doc_id": doc_id,
        })

    return sorted(citations, key=lambda c: c["page_num"])


async def query_documents(
    question: str,
    doc_ids: list[str],
    model_id: str,
    api_keys: dict,
) -> dict:
    """Query documents and return an answer with citations.
    
    Args:
        question: User's natural language question.
        doc_ids: List of document IDs to search. Empty = search all.
        model_id: LLM model identifier.
        api_keys: Dict of provider API keys.
        
    Returns:
        Dict with 'answer', 'citations', and 'model_used'.
    """
    if not question.strip():
        return {
            "answer": "Please provide a question.",
            "citations": [],
            "model_used": "",
        }

    # Configure embedding model for retrieval
    embed_model = get_embedding_model(
        provider=app_settings.embedding_provider,
        api_key=app_settings.siliconflow_api_key,
    )
    Settings.embed_model = embed_model

    # Load indexes for requested documents
    all_nodes = []

    if not doc_ids:
        # Search all indexed documents
        from app.services.indexer import list_indexed_docs
        doc_ids = list_indexed_docs()

    if not doc_ids:
        return {
            "answer": "No documents have been uploaded yet. Please upload a PDF first.",
            "citations": [],
            "model_used": model_id,
        }

    for doc_id in doc_ids:
        index = load_index(doc_id)
        if index is None:
            logger.warning(f"Index not found for doc_id: {doc_id}")
            continue

        # Create retriever
        retriever = VectorIndexRetriever(
            index=index,
            similarity_top_k=app_settings.retrieval_top_k,
        )

        # Retrieve relevant nodes
        try:
            nodes = retriever.retrieve(question)
            all_nodes.extend(nodes)
        except Exception as e:
            logger.error(f"Retrieval failed for doc {doc_id}: {e}")
            continue

    if not all_nodes:
        return {
            "answer": "I could not find relevant information in the uploaded documents to answer your question.",
            "citations": [],
            "model_used": model_id,
        }

    # Sort all nodes by relevance score (descending)
    all_nodes.sort(key=lambda n: getattr(n, "score", 0), reverse=True)
    # Keep top-k across all documents
    top_nodes = all_nodes[: app_settings.retrieval_top_k]

    # Format context
    context = _format_context(top_nodes)
    citations = _extract_citations(top_nodes)

    # Create LLM and generate answer
    try:
        llm = create_llm(model_id, api_keys)
    except ValueError as e:
        return {
            "answer": f"LLM configuration error: {str(e)}",
            "citations": [],
            "model_used": model_id,
        }

    # Build prompt
    user_message = f"""Based on the following document content, please answer the question.

Document Content:
{context}

Question: {question}

Please provide a detailed answer based ONLY on the document content above, and cite the page number(s) for each piece of information."""

    messages = [
        ChatMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
        ChatMessage(role=MessageRole.USER, content=user_message),
    ]

    try:
        response = llm.chat(messages)
        answer = response.message.content
    except Exception as e:
        logger.exception("LLM call failed")
        return {
            "answer": f"Failed to generate answer: {str(e)}",
            "citations": citations,
            "model_used": model_id,
        }

    return {
        "answer": answer,
        "citations": citations,
        "model_used": model_id,
    }
