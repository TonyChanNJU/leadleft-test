from pathlib import Path

from app.routers.upload import (
    PROCESSING_OCR,
    PROCESSING_QUEUED,
    PROCESSING_READY,
)
from app.services.document_jobs import (
    ensure_document_job,
    get_document_page_checkpoint_dir,
    get_job,
    reclaim_stale_running_jobs,
    renew_job_heartbeat,
    start_job_attempt,
)


def test_upload_creates_persistent_job(client, monkeypatch):
    from app.routers import upload as upload_router

    def _fake_run_document_pipeline(doc_id: str, file_path: str, original_filename: str) -> None:
        upload_router._update_document_status(
            doc_id,
            total_pages=1,
            indexed=True,
            processing_status=PROCESSING_READY,
            processing_message="Ready for queries.",
            current_page=None,
        )

    monkeypatch.setattr(upload_router, "_validate_pdf_bytes", lambda _content: None)
    monkeypatch.setattr(upload_router, "_run_document_pipeline", _fake_run_document_pipeline)

    upload_res = client.post(
        "/api/upload",
        files={"file": ("job.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert upload_res.status_code == 200

    doc_id = upload_res.json()["doc_id"]
    job = get_job(doc_id)
    assert job is not None
    assert job["document_id"] == doc_id
    assert job["filename"] == "job.pdf"
    assert job["status"] == "ready"
    assert job["stage"] is None
    assert job["total_pages"] == 1
    assert job["parsed_pages"] == 0


def test_recover_pending_document_jobs_reschedules_unfinished_work(isolated_data_dirs):
    from app.routers import upload as upload_router

    doc_id = "recover01"
    file_path = Path(isolated_data_dirs["upload_dir"]) / f"{doc_id}_report.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake")

    meta = {
        "doc_id": doc_id,
        "filename": "report.pdf",
        "file_path": str(file_path),
        "total_pages": 10,
        "uploaded_at": "2026-04-30T10:00:00",
        "indexed": False,
        "processing_status": PROCESSING_OCR,
        "processing_message": "Running OCR fallback.",
        "processing_error": None,
        "processed_pages": 7,
        "processing_progress_pct": None,
        "current_page": 7,
        "ocr_candidate_pages_total": 3,
        "ocr_processed_pages": 1,
        "low_quality_pages": [7, 8, 9],
        "ocr_pages": [7],
        "ocr_provider": "paddle",
    }
    upload_router.get_documents()[doc_id] = meta
    upload_router.save_registry(upload_router.get_documents())
    upload_router.bootstrap_document_jobs()

    scheduled = []

    def _fake_scheduler(job_doc_id: str, job_file_path: str, job_filename: str) -> bool:
        scheduled.append((job_doc_id, job_file_path, job_filename))
        return True

    recovered = upload_router.recover_pending_document_jobs(scheduler=_fake_scheduler)

    assert recovered == 1
    assert scheduled == [(doc_id, str(file_path), "report.pdf")]

    refreshed_meta = upload_router.get_documents()[doc_id]
    assert refreshed_meta["processing_status"] == PROCESSING_QUEUED
    assert refreshed_meta["processing_message"] == "Queued for processing."
    assert refreshed_meta["processing_error"] is None

    job = get_job(doc_id)
    assert job is not None
    assert job["status"] == "queued"
    assert job["stage"] is None
    assert job["parsed_pages"] == 7
    assert job["ocr_candidate_pages_total"] == 3
    assert job["ocr_processed_pages"] == 1


def test_delete_document_removes_persistent_job(client, monkeypatch):
    from app.routers import upload as upload_router

    def _fake_run_document_pipeline(doc_id: str, file_path: str, original_filename: str) -> None:
        upload_router._update_document_status(
            doc_id,
            total_pages=1,
            indexed=True,
            processing_status=PROCESSING_READY,
            processing_message="Ready for queries.",
            current_page=None,
        )

    monkeypatch.setattr(upload_router, "_validate_pdf_bytes", lambda _content: None)
    monkeypatch.setattr(upload_router, "_run_document_pipeline", _fake_run_document_pipeline)

    upload_res = client.post(
        "/api/upload",
        files={"file": ("delete-me.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    doc_id = upload_res.json()["doc_id"]
    assert get_job(doc_id) is not None
    checkpoint_dir = Path(get_document_page_checkpoint_dir(doc_id))
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (checkpoint_dir / "page_0001.json").write_text("{}", encoding="utf-8")

    delete_res = client.delete(f"/api/documents/{doc_id}")
    assert delete_res.status_code == 200
    assert get_job(doc_id) is None
    assert not checkpoint_dir.exists()


def test_reclaim_stale_running_job_marks_it_recoverable(isolated_data_dirs):
    meta = {
        "doc_id": "lease01",
        "filename": "lease.pdf",
        "file_path": str(Path(isolated_data_dirs["upload_dir"]) / "lease.pdf"),
        "total_pages": 3,
        "uploaded_at": "2026-05-01T10:00:00",
        "indexed": False,
        "processing_status": "parsing",
        "processing_message": "Parsing PDF structure.",
        "processing_error": None,
        "processed_pages": 1,
        "current_page": 1,
        "ocr_candidate_pages_total": 0,
        "ocr_processed_pages": 0,
        "index_total_nodes": 0,
        "index_done_nodes": 0,
        "index_total_batches": 0,
        "index_done_batches": 0,
    }
    ensure_document_job(meta)
    start_job_attempt("lease01", "parsing", "owner-a")

    assert renew_job_heartbeat("lease01", "owner-a") is True
    reclaimed = reclaim_stale_running_jobs(timeout_seconds=0)

    assert len(reclaimed) == 1
    job = get_job("lease01")
    assert job is not None
    assert job["status"] == "recoverable"
    assert job["lease_owner"] is None
