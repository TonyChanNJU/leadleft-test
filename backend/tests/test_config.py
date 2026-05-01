import os

from app.config import REPO_ROOT, Settings


def test_relative_data_paths_resolve_from_repo_root():
    settings = Settings(
        upload_dir="data/uploads",
        chroma_dir="data/chroma",
        jobs_db_path="data/document_jobs.sqlite3",
        job_artifacts_dir="data/jobs",
        ocr_cache_dir="data/cache/paddlex",
        job_lease_timeout_seconds=180,
        job_recovery_scan_interval_seconds=30,
    )

    assert settings.upload_dir == os.path.join(REPO_ROOT, "data", "uploads")
    assert settings.chroma_dir == os.path.join(REPO_ROOT, "data", "chroma")
    assert settings.jobs_db_path == os.path.join(REPO_ROOT, "data", "document_jobs.sqlite3")
    assert settings.job_artifacts_dir == os.path.join(REPO_ROOT, "data", "jobs")
    assert settings.ocr_cache_dir == os.path.join(REPO_ROOT, "data", "cache", "paddlex")
    assert settings.job_lease_timeout_seconds == 180
    assert settings.job_recovery_scan_interval_seconds == 30
