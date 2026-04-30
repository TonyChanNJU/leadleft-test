"""Run a real PaddleOCR smoke test against the Meituan broken-font sample."""

from __future__ import annotations

import os
import time

import fitz

from app.services.pdf_parser import _ocr_page_with_paddle


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _count_cjk(text: str) -> int:
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def main() -> int:
    pdf_path = os.path.join(_repo_root(), "美团2024年度报告.pdf")
    if not os.path.exists(pdf_path):
        raise SystemExit("Missing `美团2024年度报告.pdf` at repo root.")

    rows = []
    with fitz.open(pdf_path) as doc:
        for page_index in (1, 2):
            started = time.perf_counter()
            text = _ocr_page_with_paddle(doc[page_index], dpi=120)
            elapsed = time.perf_counter() - started
            cjk_chars = _count_cjk(text)
            if cjk_chars < 50:
                raise SystemExit(
                    f"OCR output looks too weak for page {page_index + 1}: "
                    f"{cjk_chars} CJK chars"
                )
            rows.append(
                {
                    "page": page_index + 1,
                    "elapsed_s": round(elapsed, 3),
                    "chars": len(text),
                    "cjk_chars": cjk_chars,
                    "preview": text[:120].replace("\n", " "),
                }
            )

    for row in rows:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
