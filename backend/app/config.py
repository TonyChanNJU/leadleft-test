"""Application configuration management using Pydantic BaseSettings."""

import os
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _resolve_repo_path(path: str) -> str:
    """Resolve relative data paths from the repository root."""
    return path if os.path.isabs(path) else os.path.join(REPO_ROOT, path)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # LLM API keys
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None

    # Embedding
    embedding_provider: str = "cloud"  # "cloud" or "local"
    siliconflow_api_key: Optional[str] = None

    # App settings
    default_llm_model: str = "gpt-4o"
    backend_port: int = 8000
    frontend_port: int = 3000

    # Data directories
    upload_dir: str = os.path.join(
        REPO_ROOT, "data", "uploads"
    )
    chroma_dir: str = os.path.join(
        REPO_ROOT, "data", "chroma"
    )
    jobs_db_path: str = os.path.join(
        REPO_ROOT, "data", "document_jobs.sqlite3"
    )
    job_artifacts_dir: str = os.path.join(
        REPO_ROOT, "data", "jobs"
    )

    # RAG settings
    chunk_size: int = 512
    chunk_overlap: int = 128
    retrieval_top_k: int = 15
    llm_context_top_k: int = 8
    max_citations: int = 3
    index_insert_batch_size: int = 64
    job_lease_timeout_seconds: int = 180
    job_recovery_scan_interval_seconds: int = 30

    # OCR fallback settings
    ocr_provider: str = "none"  # "none" or "paddle"
    ocr_dpi: int = 120
    ocr_detection_model: str = "PP-OCRv5_mobile_det"
    ocr_recognition_model: str = "PP-OCRv5_mobile_rec"
    ocr_cache_dir: str = os.path.join(
        REPO_ROOT,
        "data",
        "cache",
        "paddlex",
    )

    model_config = {
        "env_file": os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore"
    }

    @field_validator(
        "upload_dir",
        "chroma_dir",
        "jobs_db_path",
        "job_artifacts_dir",
        "ocr_cache_dir",
        mode="after",
    )
    @classmethod
    def resolve_data_paths(cls, value: str) -> str:
        """Keep relative paths stable regardless of the current working directory."""
        return _resolve_repo_path(value)

    def ensure_dirs(self) -> None:
        """Create data directories if they don't exist."""
        os.makedirs(self.upload_dir, exist_ok=True)
        os.makedirs(self.chroma_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.jobs_db_path), exist_ok=True)
        os.makedirs(self.job_artifacts_dir, exist_ok=True)


settings = Settings()
