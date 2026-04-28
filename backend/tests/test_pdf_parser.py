import os
import re

import pytest

from app.services.pdf_parser import parse_pdf

def test_parse_pdf_not_found():
    with pytest.raises(FileNotFoundError):
        parse_pdf("nonexistent.pdf")

def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _count_cjk(text: str) -> int:
    # Basic CJK Unified Ideographs range.
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def test_parse_real_tencent_pdf_smoke():
    """Align with challenge: Chinese should not be garbled; tables need not be perfect."""
    pdf_path = os.path.join(_repo_root(), "腾讯2025年度报告.pdf")
    if not os.path.exists(pdf_path):
        pytest.skip("Missing `腾讯2025年度报告.pdf` at repo root; skipping parser smoke test.")

    parsed = parse_pdf(pdf_path)
    assert parsed.total_pages > 0
    assert len(parsed.pages) == parsed.total_pages

    full_text = parsed.full_text
    assert isinstance(full_text, str)
    assert len(full_text.strip()) > 10_000  # should not be empty/near-empty

    # Chinese should be present in meaningful quantity (avoid full-page garbling).
    assert _count_cjk(full_text) > 5_000

    # Heuristic: extracted content should contain some table-like markdown rows.
    # Not strict about correctness; just ensure tables aren't always lost.
    pipe_count = full_text.count("|")
    assert pipe_count > 200
