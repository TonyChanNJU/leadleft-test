"""Query engine service with citation support.

Uses LlamaIndex to retrieve relevant chunks from ChromaDB and
generate answers with source citations (page numbers + text snippets).
"""

import logging
import re
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
8. Use as few sources as possible. Prefer the smallest number of pages that fully support the answer.
9. Do NOT cite using internal identifiers like "Source 3". Only cite using filename and page number.

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


def _source_id_to_file_page(nodes) -> dict[int, tuple[str, int]]:
    """Map 1-based Source id -> (filename, page_num) for postprocessing answer text."""
    from app.routers.upload import get_documents

    docs = get_documents()
    out: dict[int, tuple[str, int]] = {}
    for i, node in enumerate(nodes, 1):
        metadata = node.metadata or {}
        page_num = int(metadata.get("page_num") or 0)
        doc_id = metadata.get("doc_id", "")
        filename = (docs.get(doc_id) or {}).get("filename") or metadata.get("filename", "unknown")
        out[i] = (filename, page_num)
    return out


def _rewrite_source_number_citations(answer: str, source_map: dict[int, tuple[str, int]]) -> str:
    """Rewrite 'Source N, Page P' style into '(Source: filename, Page P)'."""
    if not answer or not source_map:
        return answer

    def _replace(m: re.Match) -> str:
        g1 = m.group(1)
        g2 = m.group(2)
        if g1 is None or g2 is None:
            return m.group(0)
        src_id = int(g1)
        page = int(g2)
        filename, _ = source_map.get(src_id, ("unknown", page))
        return f"(Source: {filename}, Page {page})"

    # Only match when both Source id and Page number are present.
    pattern = re.compile(r"(?:\\(|（)?\\s*Source\\s*(\\d+)\\s*,?\\s*Page\\s*(\\d+)\\s*(?:\\)|）)?", re.IGNORECASE)
    return re.sub(pattern, _replace, answer)

def _extract_citations(nodes) -> list[dict]:
    """Extract citation information from retrieved nodes (dedup per doc/page, keep best score).

    Returns all best-per-page candidates (not trimmed). Downstream selection decides final list.
    """
    from app.routers.upload import get_documents

    docs = get_documents()
    best_by_page: dict[tuple[str, int], dict] = {}

    for node in nodes:
        metadata = node.metadata or {}
        page_num = metadata.get("page_num", 0)
        doc_id = metadata.get("doc_id", "")
        filename = (docs.get(doc_id) or {}).get("filename") or metadata.get("filename", "")

        # Get a snippet (first 200 chars of the chunk)
        text_snippet = node.text[:200].strip()
        if len(node.text) > 200:
            text_snippet += "..."

        score = getattr(node, "score", 0) or 0
        key = (doc_id, int(page_num or 0))
        existing = best_by_page.get(key)
        if existing is not None and existing.get("_score", 0) >= score:
            continue

        best_by_page[key] = {
            "page_num": page_num,
            "text": text_snippet,
            "filename": filename,
            "doc_id": doc_id,
            "_score": score,
        }
    citations = list(best_by_page.values())
    citations.sort(key=lambda c: c.get("_score", 0), reverse=True)
    return citations


def _extract_cited_pages_from_answer(answer: str) -> list[int]:
    """Extract page numbers cited in the answer body.

    Supports:
    - (Source: ..., Page 4)
    - Page 4 / Page: 4
    - 第4页
    """
    if not answer:
        return []
    pages: list[int] = []
    pages += [int(x) for x in re.findall(r"\bPage\s+(\d+)\b", answer, flags=re.IGNORECASE)]
    pages += [int(x) for x in re.findall(r"\bPage\s*[:：]\s*(\d+)\b", answer, flags=re.IGNORECASE)]
    pages += [int(x) for x in re.findall(r"第\s*(\d+)\s*页", answer)]
    out: list[int] = []
    seen: set[int] = set()
    for p in pages:
        if p <= 0 or p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _select_citations_for_answer(answer: str, citations: list[dict]) -> list[dict]:
    """Return citations aligned to pages actually referenced in the answer body."""
    max_citations = max(1, int(getattr(app_settings, "max_citations", 3) or 3))
    cited_pages = _extract_cited_pages_from_answer(answer)

    # 1) If answer cites pages, prefer those pages (in cited order).
    if cited_pages:
        by_page: dict[int, dict] = {}
        for c in citations:
            p = int(c.get("page_num") or 0)
            if p > 0 and p not in by_page:
                by_page[p] = c
        picked = [by_page[p] for p in cited_pages if p in by_page]
        if picked:
            out: list[dict] = []
            # When the answer explicitly cites pages, do NOT truncate the sources list;
            # returning fewer would make the sources disagree with the answer text.
            for c in picked:
                c2 = dict(c)
                c2.pop("_score", None)
                out.append(c2)
            return out

    # 2) Fallback: take top-scoring citations, return in stable page order.
    top = citations[:max_citations]
    top_sorted = sorted(top, key=lambda c: (c.get("filename") or "", int(c.get("page_num") or 0)))
    out: list[dict] = []
    for c in top_sorted:
        c2 = dict(c)
        c2.pop("_score", None)
        out.append(c2)
    return out


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

    # Format context (cap context size to reduce noise)
    context_nodes = top_nodes[: max(1, int(getattr(app_settings, "llm_context_top_k", 8) or 8))]
    context = _format_context(context_nodes)
    # Use a wider candidate set for citations than the LLM context.
    # This allows the UI sources list to include pages that the model cited in its answer
    # even if those pages were not in the truncated context window.
    candidate_citations = _extract_citations(top_nodes)

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

Please provide a detailed answer based ONLY on the document content above, and cite the page number(s) for each piece of information.

Important:
- Use as few citations as possible.
- Include short verbatim quotes from the document when possible.
- In the answer body, DO NOT write "Source N". Always cite as: (Source: filename, Page X).
"""

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
            "citations": _select_citations_for_answer("", candidate_citations),
            "model_used": model_id,
        }

    source_map = _source_id_to_file_page(context_nodes)
    answer = _rewrite_source_number_citations(answer, source_map)

    return {
        "answer": answer,
        "citations": _select_citations_for_answer(answer, candidate_citations),
        "model_used": model_id,
    }
