import sys
import os
import time


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


# Add backend to path so we can import app (run from anywhere)
sys.path.insert(0, os.path.join(_repo_root(), "backend"))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _wait_for_indexed(doc_id: str, timeout_s: float = 180.0, interval_s: float = 1.0) -> dict:
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        res = client.get(f"/api/documents/{doc_id}")
        if res.status_code == 200:
            last = res.json()
            if last.get("indexed") is True:
                return last
        time.sleep(interval_s)
    raise AssertionError(f"Timed out waiting for indexed=true for doc_id={doc_id}; last={last}")


def run():
    from app.config import settings

    print("====================================")
    print("1. Checking API Health...")
    res = client.get("/api/health")
    assert res.status_code == 200
    print("   Health Check OK")

    print("\n2. Uploading '腾讯2025年度报告.pdf' (SiliconFlow + LlamaIndex + Chroma)...")
    pdf_path = os.path.join(_repo_root(), "腾讯2025年度报告.pdf")
    if not os.path.exists(pdf_path):
        print(f"❌ Error: Could not find {pdf_path}")
        return

    if not settings.siliconflow_api_key:
        print("❌ Error: SILICONFLOW_API_KEY is not set. This e2e requires real embedding.")
        return
    if not (
        settings.openai_api_key
        or settings.anthropic_api_key
        or settings.google_api_key
        or settings.deepseek_api_key
    ):
        print("❌ Error: No LLM API key set (OPENAI/ANTHROPIC/GOOGLE/DEEPSEEK).")
        return

    if settings.deepseek_api_key:
        model_id = "deepseek-chat"
    elif settings.openai_api_key:
        model_id = "gpt-4o"
    elif settings.anthropic_api_key:
        model_id = "claude-3-5-sonnet-20241022"
    else:
        model_id = "gemini-2.0-flash"

    with open(pdf_path, "rb") as f:
        res = client.post("/api/upload", files={"file": (pdf_path, f, "application/pdf")})

    if res.status_code != 200:
        print(f"❌ Upload Failed: {res.json()}")
        return

    data = res.json()
    doc_id = data["doc_id"]
    print(f"✅ Uploaded. doc_id: {doc_id}. Waiting for background indexing...")
    try:
        _wait_for_indexed(doc_id)
        print("✅ Indexing complete.")
    except Exception as e:
        print(f"❌ Indexing did not complete: {e}")
        return

    print("\n3. Asking challenge-aligned questions about the document...")
    questions = [
        # A (fact)
        "腾讯2025年的总收入是多少？",
        # B (summary)
        "总结一下主要业务板块。",
        # C (comparison / numeric reasoning) - English
        "How much did net profit grow from 2024 to 2025?",
        # Negative (should not hallucinate)
        "报告里是否提到“量子猫计划QCAT-2099”这个项目？如果没有请明确说明。",
    ]

    for q in questions:
        chat_payload = {
            "question": q,
            "doc_ids": [doc_id],
            "model": model_id,
        }

        chat_res = client.post("/api/chat", json=chat_payload)
        if chat_res.status_code != 200:
            print(f"❌ Chat Failed: {chat_res.json()}")
            return

        chat_data = chat_res.json()
        print("\n✅ Model Response:")
        print("------------------------------------")
        print("Question:", q)
        print(chat_data["answer"])
        print("------------------------------------")
        print("Model Used:", chat_data["model_used"])
        print("Citations Found:", len(chat_data.get("citations", [])))

        for idx, citation in enumerate(chat_data.get("citations", []), 1):
            print(f"  [{idx}] Page {citation['page_num']} excerpt: {citation['text'][:50]}...")

    print("\n====================================")
    print("END-TO-END TEST PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    run()

