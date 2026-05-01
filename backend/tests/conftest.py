import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def isolated_data_dirs(tmp_path, monkeypatch):
    """Isolate backend persistence to a per-test tmp directory."""
    from app.config import settings

    upload_dir = tmp_path / "uploads"
    chroma_dir = tmp_path / "chroma"
    jobs_db_path = tmp_path / "document_jobs.sqlite3"
    job_artifacts_dir = tmp_path / "jobs"
    upload_dir.mkdir(parents=True, exist_ok=True)
    chroma_dir.mkdir(parents=True, exist_ok=True)
    job_artifacts_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "upload_dir", str(upload_dir))
    monkeypatch.setattr(settings, "chroma_dir", str(chroma_dir))
    monkeypatch.setattr(settings, "jobs_db_path", str(jobs_db_path))
    monkeypatch.setattr(settings, "job_artifacts_dir", str(job_artifacts_dir))
    settings.ensure_dirs()

    # Reload the upload registry after changing paths.
    from app.routers import upload as upload_router

    upload_router._reset_documents_for_tests()

    # Reset cached Chroma/embedding handles to avoid cross-test interference.
    from app.services.indexer import reset_indexing_state

    reset_indexing_state()

    return {
        "upload_dir": upload_dir,
        "chroma_dir": chroma_dir,
        "jobs_db_path": jobs_db_path,
        "job_artifacts_dir": job_artifacts_dir,
    }


@pytest.fixture()
def client(isolated_data_dirs):
    from app.main import app

    return TestClient(app)


def wait_for_indexed(client: TestClient, doc_id: str, timeout_s: float = 30.0, interval_s: float = 0.5) -> dict:
    """Poll until a document is indexed or timeout."""
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
