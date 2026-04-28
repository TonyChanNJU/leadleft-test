import os

import pytest

from tests.conftest import wait_for_indexed


def _assert_has_citations(payload: dict, doc_id: str) -> None:
    citations = payload.get("citations") or []
    assert len(citations) > 0
    for c in citations:
        assert c["doc_id"] == doc_id
        assert c["filename"] == "腾讯2025年度报告.pdf"
        assert isinstance(c["page_num"], int) and c["page_num"] > 0
        assert isinstance(c["text"], str) and c["text"].strip()


@pytest.mark.e2e
def test_real_pdf_end_to_end_with_citations(client):
    """Real integration: upload Tencent annual report PDF, wait indexing, ask Q/A with citations.

    Requires:
    - repo root contains `腾讯2025年度报告.pdf`
    - env: SILICONFLOW_API_KEY + at least one LLM key (e.g. DEEPSEEK_API_KEY)
    """
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    pdf_path = os.path.join(repo_root, "腾讯2025年度报告.pdf")

    if not os.path.exists(pdf_path):
        pytest.skip("Missing `腾讯2025年度报告.pdf` at repo root; skipping real e2e test.")

    from app.config import settings

    if not settings.siliconflow_api_key:
        pytest.skip("Missing SILICONFLOW_API_KEY; skipping real e2e test.")

    if not (
        settings.openai_api_key
        or settings.anthropic_api_key
        or settings.google_api_key
        or settings.deepseek_api_key
    ):
        pytest.skip("Missing any LLM API key (OPENAI/ANTHROPIC/GOOGLE/DEEPSEEK); skipping real e2e test.")

    # Pick a model that actually has a configured API key.
    if settings.deepseek_api_key:
        model_id = "deepseek-chat"
    elif settings.openai_api_key:
        model_id = "gpt-4o"
    elif settings.anthropic_api_key:
        model_id = "claude-3-5-sonnet-20241022"
    else:
        model_id = "gemini-2.0-flash"

    with open(pdf_path, "rb") as f:
        up = client.post("/api/upload", files={"file": ("腾讯2025年度报告.pdf", f, "application/pdf")})
    assert up.status_code == 200, up.text
    doc_id = up.json()["doc_id"]

    meta = wait_for_indexed(client, doc_id, timeout_s=180.0, interval_s=1.0)
    assert meta["indexed"] is True

    # A (fact)
    qa = client.post(
        "/api/chat",
        json={
            "question": "腾讯2025年的总收入是多少？",
            "doc_ids": [doc_id],
            "model": model_id,
        },
    )
    assert qa.status_code == 200, qa.text
    pa = qa.json()
    assert isinstance(pa.get("answer"), str) and pa["answer"].strip()
    _assert_has_citations(pa, doc_id)

    # B (summary)
    qb = client.post(
        "/api/chat",
        json={
            "question": "总结一下主要业务板块。",
            "doc_ids": [doc_id],
            "model": model_id,
        },
    )
    assert qb.status_code == 200, qb.text
    pb = qb.json()
    assert isinstance(pb.get("answer"), str) and pb["answer"].strip()
    _assert_has_citations(pb, doc_id)

    # C (comparison / numeric reasoning) - English
    qc = client.post(
        "/api/chat",
        json={
            "question": "How much did net profit grow from 2024 to 2025?",
            "doc_ids": [doc_id],
            "model": model_id,
        },
    )
    assert qc.status_code == 200, qc.text
    pc = qc.json()
    assert isinstance(pc.get("answer"), str) and pc["answer"].strip()
    _assert_has_citations(pc, doc_id)

    # Ask a question that likely doesn't exist in doc: expect either no-hit refusal OR at least citations if answered.
    qneg = client.post(
        "/api/chat",
        json={
            "question": "报告里是否提到“量子猫计划QCAT-2099”这个项目？如果没有请明确说明。",
            "doc_ids": [doc_id],
            "model": model_id,
        },
    )
    assert qneg.status_code == 200, qneg.text
    pneg = qneg.json()
    citations2 = pneg.get("citations") or []
    if len(citations2) == 0:
        assert "could not find relevant information" in (pneg.get("answer") or "").lower()
    else:
        for c in citations2:
            assert c["doc_id"] == doc_id
            assert isinstance(c["page_num"], int) and c["page_num"] > 0

