import os

from app.config import REPO_ROOT, Settings


def test_relative_data_paths_resolve_from_repo_root():
    settings = Settings(
        upload_dir="data/uploads",
        chroma_dir="data/chroma",
        ocr_cache_dir="data/cache/paddlex",
    )

    assert settings.upload_dir == os.path.join(REPO_ROOT, "data", "uploads")
    assert settings.chroma_dir == os.path.join(REPO_ROOT, "data", "chroma")
    assert settings.ocr_cache_dir == os.path.join(REPO_ROOT, "data", "cache", "paddlex")
