"""Application configuration management using Pydantic BaseSettings."""

import os
from typing import Optional

from pydantic_settings import BaseSettings


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
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "uploads"
    )
    chroma_dir: str = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "chroma"
    )

    # RAG settings
    chunk_size: int = 512
    chunk_overlap: int = 128
    retrieval_top_k: int = 5

    model_config = {
        "env_file": os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore"
    }

    def ensure_dirs(self) -> None:
        """Create data directories if they don't exist."""
        os.makedirs(self.upload_dir, exist_ok=True)
        os.makedirs(self.chroma_dir, exist_ok=True)


settings = Settings()
