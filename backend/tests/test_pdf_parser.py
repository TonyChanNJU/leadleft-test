import os
import re

import pytest
import fitz

from app.services.pdf_parser import (
    ParseProgress,
    PageContent,
    PageDiagnostics,
    ParsedDocument,
    _diagnose_page,
    _extract_text_from_paddle_result,
    _maybe_ocr_page,
    parse_pdf,
)


def test_parse_pdf_not_found():
    with pytest.raises(FileNotFoundError):
        parse_pdf("nonexistent.pdf")


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _repo_pdf(filename: str) -> str:
    return os.path.join(_repo_root(), filename)


def _count_cjk(text: str) -> int:
    # Basic CJK Unified Ideographs range.
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def test_page_diagnostics_flags_image_heavy_low_text():
    blocks = [{"type": 1, "bbox": (0, 0, 100, 80)}]
    diagnostics = _diagnose_page("  ", blocks, [], fitz.Rect(0, 0, 100, 100))

    assert diagnostics.is_low_quality is True
    assert "image_heavy_low_text" in diagnostics.reasons
    assert "near_empty_text_with_images" in diagnostics.reasons
    assert diagnostics.image_area_ratio == 0.8


def test_page_diagnostics_flags_font_mapping_noise():
    diagnostics = _diagnose_page(
        "(cid:1234) \ufffd " + "\ue000" * 80,
        [{"type": 0, "lines": [{"spans": [{"font": "MHeiHK-Light"}]}]}],
        [],
        fitz.Rect(0, 0, 100, 100),
    )

    assert diagnostics.is_low_quality is True
    assert "cid_markers" in diagnostics.reasons
    assert "replacement_characters" in diagnostics.reasons
    assert "private_use_glyphs" in diagnostics.reasons
    assert diagnostics.font_names == ["MHeiHK-Light"]


def test_extract_text_from_paddle_result_shapes():
    classic_result = [[[[0, 0], [1, 0]], ("腾讯控股", 0.99)]]
    dict_result = [{"rec_texts": ["收入", "利润"]}]

    assert _extract_text_from_paddle_result(classic_result) == "腾讯控股"
    assert _extract_text_from_paddle_result(dict_result) == "收入\n利润"


def test_ocr_fallback_uses_mocked_paddle_text(monkeypatch):
    diagnostics = PageDiagnostics(
        text_length=0,
        cjk_chars=0,
        cjk_ratio=0.0,
        cid_marker_count=0,
        replacement_char_count=0,
        private_use_count=0,
        suspicious_symbol_ratio=0.0,
        image_count=1,
        image_area_ratio=0.8,
        table_area_ratio=0.0,
        is_low_quality=True,
        reasons=["image_heavy_low_text"],
    )
    monkeypatch.setattr(
        "app.services.pdf_parser._ocr_page_with_paddle",
        lambda _page, _dpi: "识别文本",
    )

    text = _maybe_ocr_page(object(), diagnostics, "paddle", 220)

    assert text == "识别文本"
    assert diagnostics.ocr_attempted is True
    assert diagnostics.ocr_succeeded is True


def test_parsed_document_quality_page_lists():
    diagnostics = PageDiagnostics(
        text_length=0,
        cjk_chars=0,
        cjk_ratio=0.0,
        cid_marker_count=0,
        replacement_char_count=0,
        private_use_count=0,
        suspicious_symbol_ratio=0.0,
        image_count=1,
        image_area_ratio=0.8,
        table_area_ratio=0.0,
        is_low_quality=True,
        reasons=["image_heavy_low_text"],
        ocr_succeeded=True,
    )
    parsed = ParsedDocument(
        filename="x.pdf",
        total_pages=1,
        pages=[PageContent(page_num=1, text="识别文本", diagnostics=diagnostics, extraction_method="ocr")],
    )

    assert parsed.low_quality_pages == [1]
    assert parsed.ocr_pages == [1]


def test_parse_real_tencent_pdf_smoke():
    """Align with challenge: Chinese should not be garbled; tables need not be perfect."""
    pdf_path = _repo_pdf("腾讯2025年度报告.pdf")
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


def test_parse_real_meituan_pdf_flags_font_mapping_failures():
    """Meituan 2024 is a real broken CJK font-map sample that should be diagnosed."""
    pdf_path = _repo_pdf("美团2024年度报告.pdf")
    if not os.path.exists(pdf_path):
        pytest.skip("Missing `美团2024年度报告.pdf` at repo root; skipping diagnostic smoke test.")

    parsed = parse_pdf(pdf_path, ocr_provider="none")

    assert parsed.total_pages > 0
    assert len(parsed.low_quality_pages) >= int(parsed.total_pages * 0.8)

    page_2 = parsed.pages[1]
    assert page_2.diagnostics is not None
    assert page_2.diagnostics.is_low_quality is True
    assert "replacement_characters" in page_2.diagnostics.reasons
    assert "possible_cjk_font_mapping_failure" in page_2.diagnostics.reasons
    assert any(font.startswith("MHeiHK") for font in page_2.diagnostics.font_names)
    assert _count_cjk(page_2.text) == 0


def test_parse_real_meituan_pdf_triggers_mocked_ocr_fallback(monkeypatch):
    """When OCR is enabled, low-quality Meituan pages should use the fallback path."""
    pdf_path = _repo_pdf("美团2024年度报告.pdf")
    if not os.path.exists(pdf_path):
        pytest.skip("Missing `美团2024年度报告.pdf` at repo root; skipping OCR fallback smoke test.")

    calls = []

    def fake_ocr_page(page, dpi):
        calls.append((page.number + 1, dpi))
        return f"识别文本第{page.number + 1}页"

    monkeypatch.setattr("app.services.pdf_parser._ocr_page_with_paddle", fake_ocr_page)

    parsed = parse_pdf(pdf_path, ocr_provider="paddle", ocr_dpi=180)

    assert parsed.ocr_pages
    assert 2 in parsed.ocr_pages
    assert len(calls) == len(parsed.low_quality_pages)
    assert calls[0] == (2, 180)
    assert parsed.pages[1].extraction_method == "ocr"
    assert parsed.pages[1].text == "识别文本第2页"


def test_parse_pdf_reports_parsing_and_ocr_progress(tmp_path, monkeypatch):
    pdf_path = tmp_path / "progress.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    doc.save(pdf_path)
    doc.close()

    low_quality = PageDiagnostics(
        text_length=0,
        cjk_chars=0,
        cjk_ratio=0.0,
        cid_marker_count=0,
        replacement_char_count=1,
        private_use_count=0,
        suspicious_symbol_ratio=0.0,
        image_count=0,
        image_area_ratio=0.0,
        table_area_ratio=0.0,
        is_low_quality=True,
        reasons=["replacement_characters"],
    )
    normal_quality = PageDiagnostics(
        text_length=10,
        cjk_chars=5,
        cjk_ratio=0.5,
        cid_marker_count=0,
        replacement_char_count=0,
        private_use_count=0,
        suspicious_symbol_ratio=0.0,
        image_count=0,
        image_area_ratio=0.0,
        table_area_ratio=0.0,
        is_low_quality=False,
        reasons=[],
    )

    def fake_extract_native_page_content(_fitz_page, _plumber_page, page_num):
        diagnostics = low_quality if page_num == 1 else normal_quality
        return PageContent(page_num=page_num, text=f"page-{page_num}", diagnostics=diagnostics)

    progress_events: list[ParseProgress] = []

    monkeypatch.setattr(
        "app.services.pdf_parser._extract_native_page_content",
        fake_extract_native_page_content,
    )
    monkeypatch.setattr(
        "app.services.pdf_parser._maybe_ocr_page",
        lambda *_args, **_kwargs: "OCR page 1",
    )

    parsed = parse_pdf(
        str(pdf_path),
        ocr_provider="paddle",
        progress_callback=progress_events.append,
    )

    assert parsed.pages[0].text == "OCR page 1"
    assert parsed.pages[0].extraction_method == "ocr"

    parsing_events = [event for event in progress_events if event.stage == "parsing"]
    ocr_events = [event for event in progress_events if event.stage == "ocr"]

    assert [event.processed_pages for event in parsing_events] == [0, 1, 2]
    assert ocr_events[0].ocr_candidate_pages_total == 1
    assert ocr_events[-1].ocr_processed_pages == 1
    assert ocr_events[-1].processed_pages == 1
