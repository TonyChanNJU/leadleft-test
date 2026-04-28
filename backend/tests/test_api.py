def test_health_check(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.0.0"}

def test_get_documents(client):
    response = client.get("/api/documents")
    assert response.status_code == 200
    assert "documents" in response.json()


def test_upload_rejects_non_pdf_filename(client):
    res = client.post(
        "/api/upload",
        files={"file": ("not-a-pdf.txt", b"hello", "text/plain")},
    )
    assert res.status_code == 400


def test_upload_rejects_wrong_content_type(client):
    # Filename endswith .pdf but content-type isn't application/pdf
    res = client.post(
        "/api/upload",
        files={"file": ("x.pdf", b"%PDF-1.4", "text/plain")},
    )
    assert res.status_code == 400


def test_upload_rejects_empty_file(client):
    res = client.post(
        "/api/upload",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert res.status_code == 400


def test_upload_deduplicates_by_filename(client, monkeypatch):
    from app.routers import upload as upload_router
    from app.services.pdf_parser import ParsedDocument, PageContent

    monkeypatch.setattr(
        upload_router,
        "parse_pdf",
        lambda _: ParsedDocument(filename="x.pdf", total_pages=1, pages=[PageContent(page_num=1, text="hi")]),
    )

    # Make the background indexing task a no-op (avoid Chroma/embedding in unit tests)
    def _fake_run_index_build(doc_id: str, file_path: str, original_filename: str) -> None:
        upload_router.get_documents()[doc_id]["indexed"] = True
        upload_router.save_registry(upload_router.get_documents())

    monkeypatch.setattr(upload_router, "_run_index_build", _fake_run_index_build)

    res1 = client.post(
        "/api/upload",
        files={"file": ("dup.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert res1.status_code == 200

    res2 = client.post(
        "/api/upload",
        files={"file": ("dup.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert res2.status_code == 409


def test_documents_get_and_pdf_headers(client, monkeypatch):
    from app.routers import upload as upload_router
    from app.services.pdf_parser import ParsedDocument, PageContent

    monkeypatch.setattr(
        upload_router,
        "parse_pdf",
        lambda path: ParsedDocument(filename=path, total_pages=1, pages=[PageContent(page_num=1, text="hi")]),
    )

    def _fake_run_index_build(doc_id: str, file_path: str, original_filename: str) -> None:
        upload_router.get_documents()[doc_id]["indexed"] = True
        upload_router.save_registry(upload_router.get_documents())

    monkeypatch.setattr(upload_router, "_run_index_build", _fake_run_index_build)

    upload_res = client.post(
        "/api/upload",
        files={"file": ("one.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert upload_res.status_code == 200
    doc_id = upload_res.json()["doc_id"]

    list_res = client.get("/api/documents")
    assert list_res.status_code == 200
    docs = list_res.json()["documents"]
    assert any(d["doc_id"] == doc_id for d in docs)

    meta_res = client.get(f"/api/documents/{doc_id}")
    assert meta_res.status_code == 200
    meta = meta_res.json()
    assert meta["doc_id"] == doc_id
    assert meta["filename"] == "one.pdf"

    pdf_res = client.get(f"/api/documents/{doc_id}/pdf")
    assert pdf_res.status_code == 200
    assert "inline" in (pdf_res.headers.get("content-disposition") or "")
    assert (pdf_res.headers.get("x-content-type-options") or "").lower() == "nosniff"


def test_chat_rejects_empty_question(client):
    res = client.post("/api/chat", json={"question": "   ", "doc_ids": [], "model": ""})
    assert res.status_code == 400


def test_chat_rejects_unsupported_model(client):
    res = client.post("/api/chat", json={"question": "hi", "doc_ids": [], "model": "not-a-model"})
    assert res.status_code == 400


def test_chat_no_documents_returns_prompt(client, monkeypatch):
    # With no indexed docs, the query layer returns a fixed message without needing any API keys
    from app.services import query_engine as qe
    from llama_index.core.embeddings import BaseEmbedding

    class _DummyEmbedding(BaseEmbedding):
        def _get_query_embedding(self, query: str) -> list[float]:
            return [0.0]

        async def _aget_query_embedding(self, query: str) -> list[float]:
            return [0.0]

        def _get_text_embedding(self, text: str) -> list[float]:
            return [0.0]

        async def _aget_text_embedding(self, text: str) -> list[float]:
            return [0.0]

        def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] for _ in texts]

        async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] for _ in texts]

    monkeypatch.setattr(qe, "get_embedding_model", lambda *args, **kwargs: _DummyEmbedding())
    res = client.post("/api/chat", json={"question": "hi", "doc_ids": [], "model": "gpt-4o"})
    assert res.status_code == 200
    payload = res.json()
    assert isinstance(payload.get("answer"), str)
    assert payload.get("citations") == []
