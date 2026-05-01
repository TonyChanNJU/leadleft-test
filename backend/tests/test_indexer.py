import pytest

from llama_index.core.embeddings import BaseEmbedding

from app.routers.upload import PROCESSING_INDEXING, _public_document_meta
from app.services.indexer import (
    IndexBuildProgress,
    _get_chroma_client,
    build_index,
    build_nodes,
    list_indexed_docs,
    load_index,
    reset_indexing_state,
)
from app.services.pdf_parser import PageContent, PageDiagnostics, ParsedDocument, TableData


class _DummyEmbedding(BaseEmbedding):
    def _get_query_embedding(self, query: str) -> list[float]:
        return [float(len(query) or 1), 0.0]

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        return [float(len(text) or 1), 1.0]

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._get_text_embedding(text)

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return [self._get_text_embedding(text) for text in texts]

    async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return self._get_text_embeddings(texts)


def _sample_parsed_document() -> ParsedDocument:
    diagnostics = PageDiagnostics(
        text_length=120,
        cjk_chars=20,
        cjk_ratio=0.16,
        cid_marker_count=0,
        replacement_char_count=0,
        private_use_count=0,
        suspicious_symbol_ratio=0.0,
        image_count=0,
        image_area_ratio=0.0,
        table_area_ratio=0.2,
        is_low_quality=False,
        reasons=[],
    )
    return ParsedDocument(
        filename="report.pdf",
        total_pages=2,
        pages=[
            PageContent(
                page_num=1,
                text="Revenue increased significantly in the first quarter. " * 5,
                native_text="Revenue increased significantly in the first quarter. " * 5,
                diagnostics=diagnostics,
            ),
            PageContent(
                page_num=2,
                text="Operating metrics summary.",
                native_text="Operating metrics summary.",
                diagnostics=diagnostics,
                tables=[
                    TableData(
                        page_num=2,
                        bbox=(0, 0, 100, 100),
                        markdown="| Metric | Value |\n| --- | --- |\n| GMV | 123 |",
                    )
                ],
            ),
        ],
    )


def test_build_nodes_assigns_stable_ids_and_preserves_table_nodes():
    parsed_doc = _sample_parsed_document()

    nodes = build_nodes("doc123", parsed_doc)

    assert nodes
    table_nodes = [node for node in nodes if (node.metadata or {}).get("content_type") == "table"]
    text_nodes = [node for node in nodes if (node.metadata or {}).get("content_type") != "table"]

    assert table_nodes
    assert table_nodes[0].text.startswith("| Metric | Value |")
    assert table_nodes[0].node_id == "doc123:page:2:table:0"
    assert all(node.node_id.startswith("doc123:page:") for node in text_nodes)


def test_build_index_reports_batch_progress_and_loads_index(isolated_data_dirs, monkeypatch):
    from app.services import indexer
    from app.config import settings

    parsed_doc = _sample_parsed_document()
    reset_indexing_state()
    monkeypatch.setattr(indexer, "get_embedding_model", lambda *args, **kwargs: _DummyEmbedding())
    monkeypatch.setattr(settings, "index_insert_batch_size", 2)

    progress_events: list[IndexBuildProgress] = []
    index = build_index("doc456", parsed_doc, progress_callback=progress_events.append)

    assert index is not None
    assert progress_events
    assert progress_events[0].processed_nodes == 0
    assert progress_events[0].processed_batches == 0
    assert progress_events[-1].processed_nodes == progress_events[-1].total_nodes
    assert progress_events[-1].processed_batches == progress_events[-1].total_batches
    assert progress_events[-1].total_batches >= 2

    collection = _get_chroma_client().get_collection("doc_doc456")
    assert collection.count() == progress_events[-1].total_nodes
    assert "doc456" in list_indexed_docs()
    assert load_index("doc456") is not None


def test_build_index_resumes_from_completed_batches(isolated_data_dirs, monkeypatch):
    from app.services import indexer
    from app.config import settings

    parsed_doc = _sample_parsed_document()
    reset_indexing_state()
    monkeypatch.setattr(indexer, "get_embedding_model", lambda *args, **kwargs: _DummyEmbedding())
    monkeypatch.setattr(settings, "index_insert_batch_size", 2)

    interrupted_progress: list[IndexBuildProgress] = []

    def fail_after_first_batch(progress: IndexBuildProgress) -> None:
        interrupted_progress.append(progress)
        if progress.processed_batches == 1:
            raise RuntimeError("Simulated crash after first batch")

    with pytest.raises(RuntimeError, match="Simulated crash"):
        build_index("doc_resume", parsed_doc, progress_callback=fail_after_first_batch)

    assert interrupted_progress[-1].processed_batches == 1
    partial_count = _get_chroma_client().get_collection("doc_doc_resume").count()
    assert partial_count == interrupted_progress[-1].processed_nodes

    resumed_progress: list[IndexBuildProgress] = []
    build_index(
        "doc_resume",
        parsed_doc,
        progress_callback=resumed_progress.append,
        resume_from_done_batches=interrupted_progress[-1].processed_batches,
        resume_from_done_nodes=interrupted_progress[-1].processed_nodes,
    )

    final = resumed_progress[-1]
    assert resumed_progress[0].processed_batches == 1
    assert resumed_progress[0].processed_nodes == interrupted_progress[-1].processed_nodes
    assert final.processed_batches == final.total_batches
    assert final.processed_nodes == final.total_nodes
    assert _get_chroma_client().get_collection("doc_doc_resume").count() == final.total_nodes


def test_public_document_meta_reports_indexing_progress_percentage():
    meta = _public_document_meta(
        {
            "doc_id": "doc789",
            "filename": "report.pdf",
            "uploaded_at": "2026-05-01T10:00:00",
            "indexed": False,
            "processing_status": PROCESSING_INDEXING,
            "processing_message": "Building vector index.",
            "processed_pages": 2,
            "index_total_nodes": 8,
            "index_done_nodes": 3,
            "index_total_batches": 4,
            "index_done_batches": 2,
            "ocr_candidate_pages_total": 0,
            "ocr_processed_pages": 0,
            "ocr_pages": [],
            "low_quality_pages": [],
        }
    )

    assert meta["processing_progress_pct"] == 38
    assert meta["index_total_nodes"] == 8
    assert meta["index_done_batches"] == 2
