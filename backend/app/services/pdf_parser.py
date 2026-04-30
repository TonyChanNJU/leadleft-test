"""PDF parsing service using PyMuPDF for text and pdfplumber for tables.

Handles multi-column layouts, tables, and Chinese text. Outputs structured
page-by-page content with metadata for downstream indexing.
"""

import io
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

import fitz  # PyMuPDF
import pdfplumber

from app.config import settings


_paddle_ocr_instances: dict[tuple[str, str], object] = {}


@dataclass
class ParseProgress:
    """Progress update emitted while parsing a PDF document."""
    stage: str
    total_pages: int
    processed_pages: int
    current_page: Optional[int] = None
    ocr_candidate_pages_total: int = 0
    ocr_processed_pages: int = 0


ParseProgressCallback = Callable[[ParseProgress], None]


@dataclass
class TableData:
    """Extracted table data with position info."""
    page_num: int
    bbox: tuple  # (x0, y0, x1, y1)
    markdown: str  # Table rendered as markdown


@dataclass
class PageDiagnostics:
    """Page-level extraction quality signals."""
    text_length: int
    cjk_chars: int
    cjk_ratio: float
    cid_marker_count: int
    replacement_char_count: int
    private_use_count: int
    suspicious_symbol_ratio: float
    image_count: int
    image_area_ratio: float
    table_area_ratio: float
    font_names: list[str] = field(default_factory=list)
    is_low_quality: bool = False
    reasons: list[str] = field(default_factory=list)
    ocr_attempted: bool = False
    ocr_succeeded: bool = False
    ocr_error: Optional[str] = None


@dataclass
class PageContent:
    """Content extracted from a single PDF page."""
    page_num: int  # 1-indexed
    text: str
    tables: list[TableData] = field(default_factory=list)
    diagnostics: Optional[PageDiagnostics] = None
    extraction_method: str = "native"

    @property
    def full_content(self) -> str:
        """Combine text and tables into a single string."""
        if not self.tables:
            return self.text
        # Already merged during extraction
        return self.text


@dataclass
class ParsedDocument:
    """Complete parsed document."""
    filename: str
    total_pages: int
    pages: list[PageContent]

    @property
    def full_text(self) -> str:
        """Get all text content across all pages."""
        parts = []
        for page in self.pages:
            parts.append(f"[Page {page.page_num}]\n{page.full_content}")
        return "\n\n".join(parts)

    @property
    def low_quality_pages(self) -> list[int]:
        """Return pages whose native extraction quality looks suspicious."""
        return [
            page.page_num
            for page in self.pages
            if page.diagnostics and page.diagnostics.is_low_quality
        ]

    @property
    def ocr_pages(self) -> list[int]:
        """Return pages where OCR fallback contributed text."""
        return [
            page.page_num
            for page in self.pages
            if page.diagnostics and page.diagnostics.ocr_succeeded
        ]


def _table_to_markdown(table_data: list[list[Optional[str]]]) -> str:
    """Convert a 2D table array to markdown format.
    
    Args:
        table_data: 2D list of cell values from pdfplumber.
        
    Returns:
        Markdown-formatted table string.
    """
    if not table_data or len(table_data) < 1:
        return ""

    # Clean cell values
    def clean_cell(cell: Optional[str]) -> str:
        if cell is None:
            return ""
        # Normalize whitespace but preserve content
        return re.sub(r"\s+", " ", str(cell).strip())

    rows = [[clean_cell(cell) for cell in row] for row in table_data]

    # Calculate column widths
    num_cols = max(len(row) for row in rows)
    # Pad rows to same length
    for row in rows:
        while len(row) < num_cols:
            row.append("")

    # Build markdown table
    lines = []
    # Header row
    header = rows[0]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * num_cols) + " |")
    # Data rows
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def _extract_tables_from_page(
    plumber_page: pdfplumber.page.Page, page_num: int
) -> list[TableData]:
    """Extract tables from a page using pdfplumber.
    
    Args:
        plumber_page: A pdfplumber page object.
        page_num: 1-indexed page number.
        
    Returns:
        List of TableData with position and markdown content.
    """
    tables = []
    detected = plumber_page.find_tables()

    for table_obj in detected:
        try:
            table_data = table_obj.extract()
            if not table_data or len(table_data) < 2:
                continue

            markdown = _table_to_markdown(table_data)
            if not markdown.strip():
                continue

            bbox = table_obj.bbox  # (x0, y0, x1, y1)
            tables.append(
                TableData(page_num=page_num, bbox=bbox, markdown=markdown)
            )
        except Exception:
            # Skip tables that fail to extract
            continue

    return tables


def _is_in_table_region(
    block_bbox: tuple, tables: list[TableData], tolerance: float = 5.0
) -> bool:
    """Check if a text block overlaps with any table region.
    
    Args:
        block_bbox: (x0, y0, x1, y1) of the text block.
        tables: List of detected tables with bboxes.
        tolerance: Pixel tolerance for overlap detection.
        
    Returns:
        True if the block is inside a table region.
    """
    bx0, by0, bx1, by1 = block_bbox
    for table in tables:
        tx0, ty0, tx1, ty1 = table.bbox
        # Check overlap with tolerance
        if (
            bx0 >= tx0 - tolerance
            and by0 >= ty0 - tolerance
            and bx1 <= tx1 + tolerance
            and by1 <= ty1 + tolerance
        ):
            return True
    return False


def _area_ratio(bboxes: list[tuple], page_rect: fitz.Rect) -> float:
    """Compute a capped area ratio for page-space bounding boxes."""
    page_area = max(float(page_rect.width * page_rect.height), 1.0)
    total = 0.0
    for bbox in bboxes:
        try:
            rect = fitz.Rect(bbox) & page_rect
            if not rect.is_empty:
                total += max(rect.width, 0.0) * max(rect.height, 0.0)
        except Exception:
            continue
    return min(total / page_area, 1.0)


def _count_cjk(text: str) -> int:
    """Count basic CJK Unified Ideographs."""
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def _count_private_use(text: str) -> int:
    """Count private-use glyphs, a common signal for broken font maps."""
    return sum(1 for ch in text if "\ue000" <= ch <= "\uf8ff")


def _suspicious_symbol_ratio(text: str) -> float:
    """Estimate how much extracted text looks like non-content glyph noise."""
    visible = [ch for ch in text if not ch.isspace()]
    if not visible:
        return 0.0

    common_punctuation = set(
        ".,;:!?()[]{}<>+-=*/%$#@&_|\\\"'`~"
        "，。；：！？（）【】《》、"
    )
    suspicious = 0
    for ch in visible:
        if ch.isalnum() or "\u4e00" <= ch <= "\u9fff" or ch in common_punctuation:
            continue
        suspicious += 1

    return suspicious / len(visible)


def _collect_font_names(blocks: list[dict]) -> list[str]:
    """Collect text span font names from PyMuPDF blocks."""
    fonts: set[str] = set()
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                font = str(span.get("font") or "").strip()
                if font:
                    fonts.add(font)
    return sorted(fonts)


def _diagnose_page(
    text: str,
    blocks: list[dict],
    tables: list[TableData],
    page_rect: fitz.Rect,
) -> PageDiagnostics:
    """Build extraction quality diagnostics for one page."""
    text_length = len(text.strip())
    cjk_chars = _count_cjk(text)
    cjk_ratio = cjk_chars / text_length if text_length else 0.0
    cid_marker_count = len(re.findall(r"\(cid:\d+\)", text, flags=re.IGNORECASE))
    replacement_char_count = text.count("\ufffd")
    private_use_count = _count_private_use(text)
    suspicious_symbol_ratio = _suspicious_symbol_ratio(text)
    image_bboxes = [
        tuple(block.get("bbox", ()))
        for block in blocks
        if block.get("type") == 1 and block.get("bbox")
    ]
    table_bboxes = [table.bbox for table in tables]

    reasons: list[str] = []
    image_area_ratio = _area_ratio(image_bboxes, page_rect)
    table_area_ratio = _area_ratio(table_bboxes, page_rect)

    if text_length < 80 and image_area_ratio > 0.35:
        reasons.append("image_heavy_low_text")
    if text_length < 40 and image_bboxes:
        reasons.append("near_empty_text_with_images")
    if cid_marker_count:
        reasons.append("cid_markers")
    if replacement_char_count:
        reasons.append("replacement_characters")
    if private_use_count:
        reasons.append("private_use_glyphs")
    if text_length >= 80 and suspicious_symbol_ratio > 0.35:
        reasons.append("high_symbol_noise")
    if text_length >= 120 and cjk_chars == 0 and suspicious_symbol_ratio > 0.20:
        reasons.append("possible_cjk_font_mapping_failure")

    return PageDiagnostics(
        text_length=text_length,
        cjk_chars=cjk_chars,
        cjk_ratio=round(cjk_ratio, 4),
        cid_marker_count=cid_marker_count,
        replacement_char_count=replacement_char_count,
        private_use_count=private_use_count,
        suspicious_symbol_ratio=round(suspicious_symbol_ratio, 4),
        image_count=len(image_bboxes),
        image_area_ratio=round(image_area_ratio, 4),
        table_area_ratio=round(table_area_ratio, 4),
        font_names=_collect_font_names(blocks),
        is_low_quality=bool(reasons),
        reasons=reasons,
    )


def _extract_text_from_paddle_result(result: object) -> str:
    """Extract recognized text from common PaddleOCR result shapes."""
    texts: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, str):
            if value.strip():
                texts.append(value.strip())
            return
        if isinstance(value, dict):
            for key in ("rec_texts", "text", "texts"):
                found = value.get(key)
                if isinstance(found, list):
                    for item in found:
                        visit(item)
                elif isinstance(found, str):
                    visit(found)
            return
        if isinstance(value, (list, tuple)):
            # Classic PaddleOCR shape: [bbox, (text, score)].
            if len(value) == 2 and isinstance(value[1], tuple) and value[1]:
                visit(value[1][0])
                return
            for item in value:
                visit(item)

    visit(result)
    return "\n".join(dict.fromkeys(texts))


def _prepare_paddle_env() -> None:
    """Configure PaddleX cache paths before importing PaddleOCR."""
    os.makedirs(settings.ocr_cache_dir, exist_ok=True)
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", settings.ocr_cache_dir)
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


def _get_paddle_ocr():
    """Get a cached PaddleOCR instance."""
    detection_model = settings.ocr_detection_model.strip()
    recognition_model = settings.ocr_recognition_model.strip()
    cache_key = (detection_model, recognition_model)
    if cache_key in _paddle_ocr_instances:
        return _paddle_ocr_instances[cache_key]

    _prepare_paddle_env()

    try:
        from paddleocr import PaddleOCR
    except Exception as e:
        raise RuntimeError(
            "PaddleOCR is not installed. Install `paddleocr` and set "
            "OCR_PROVIDER=paddle to enable OCR fallback."
        ) from e

    try:
        kwargs = {
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
        }
        if detection_model:
            kwargs["text_detection_model_name"] = detection_model
        if recognition_model:
            kwargs["text_recognition_model_name"] = recognition_model
        if not detection_model and not recognition_model:
            kwargs["lang"] = "ch"

        _paddle_ocr_instances[cache_key] = PaddleOCR(**kwargs)
    except TypeError:
        _paddle_ocr_instances[cache_key] = PaddleOCR(lang="ch", use_angle_cls=True)

    return _paddle_ocr_instances[cache_key]


def _ocr_page_with_paddle(fitz_page: fitz.Page, dpi: int) -> str:
    """Run PaddleOCR on a rendered page image."""
    pix = fitz_page.get_pixmap(dpi=dpi, alpha=False)
    image_bytes = pix.tobytes("png")

    try:
        from PIL import Image
        import numpy as np

        image = np.array(Image.open(io.BytesIO(image_bytes)))
    except Exception as e:
        raise RuntimeError("PaddleOCR fallback requires Pillow and numpy.") from e

    ocr = _get_paddle_ocr()
    if hasattr(ocr, "ocr"):
        result = ocr.ocr(image)
    elif hasattr(ocr, "predict"):
        result = ocr.predict(image)
    else:
        raise RuntimeError("Unsupported PaddleOCR API: no `ocr` or `predict` method.")

    return _extract_text_from_paddle_result(result)


def _maybe_ocr_page(
    fitz_page: fitz.Page,
    diagnostics: PageDiagnostics,
    provider: str,
    dpi: int,
    on_ocr_start: Optional[Callable[[], None]] = None,
) -> str:
    """Run OCR if the page was flagged as low quality and OCR is enabled."""
    if not diagnostics.is_low_quality:
        return ""

    normalized_provider = provider.strip().lower()
    if normalized_provider in ("", "none", "off", "disabled"):
        return ""
    if normalized_provider != "paddle":
        diagnostics.ocr_attempted = True
        diagnostics.ocr_error = f"Unsupported OCR_PROVIDER={provider!r}"
        return ""

    diagnostics.ocr_attempted = True
    if on_ocr_start is not None:
        on_ocr_start()
    try:
        text = _ocr_page_with_paddle(fitz_page, dpi).strip()
    except Exception as e:
        diagnostics.ocr_error = str(e)
        return ""

    diagnostics.ocr_succeeded = bool(text)
    return text


def _extract_native_page_content(
    fitz_page: fitz.Page,
    plumber_page: pdfplumber.page.Page,
    page_num: int,
) -> PageContent:
    """Extract native content from a single page, merging text and tables.
    
    Strategy:
    1. Use pdfplumber to detect table regions and extract structured tables
    2. Use PyMuPDF to extract text blocks (better for multi-column, CJK)
    3. Exclude text blocks that fall within table regions
    4. Merge non-table text and table markdown in reading order (top to bottom)
    
    Args:
        fitz_page: A PyMuPDF page object.
        plumber_page: A pdfplumber page object for the same page.
        page_num: 1-indexed page number.
        
    Returns:
        PageContent with merged text and tables.
    """
    # Step 1: Extract tables with pdfplumber
    tables = _extract_tables_from_page(plumber_page, page_num)

    # Step 2: Extract text blocks with PyMuPDF
    # "dict" mode gives us detailed block info with positions
    blocks = fitz_page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

    # Step 3: Build content segments ordered by vertical position
    segments: list[tuple[float, str]] = []  # (y_position, content)

    for block in blocks:
        if block.get("type") != 0:  # 0 = text block
            continue

        block_bbox = (block["bbox"][0], block["bbox"][1], block["bbox"][2], block["bbox"][3])

        # Skip if this block is inside a table region
        if tables and _is_in_table_region(block_bbox, tables):
            continue

        # Extract text from spans
        text_parts = []
        for line in block.get("lines", []):
            line_text = ""
            for span in line.get("spans", []):
                line_text += span.get("text", "")
            if line_text.strip():
                text_parts.append(line_text.strip())

        if text_parts:
            text = "\n".join(text_parts)
            y_pos = block["bbox"][1]  # Top y coordinate
            segments.append((y_pos, text))

    # Step 4: Insert table markdown at proper positions
    for table in tables:
        y_pos = table.bbox[1]  # Top y of table
        segments.append((y_pos, f"\n{table.markdown}\n"))

    # Step 5: Sort by y position (top to bottom reading order)
    segments.sort(key=lambda s: s[0])

    # Combine
    merged_text = "\n\n".join(content for _, content in segments)
    diagnostics = _diagnose_page(merged_text, blocks, tables, fitz_page.rect)

    return PageContent(
        page_num=page_num,
        text=merged_text,
        tables=tables,
        diagnostics=diagnostics,
        extraction_method="native",
    )


def parse_pdf(
    file_path: str,
    ocr_provider: Optional[str] = None,
    ocr_dpi: Optional[int] = None,
    progress_callback: Optional[ParseProgressCallback] = None,
) -> ParsedDocument:
    """Parse a PDF file, extracting text and tables from all pages.
    
    Uses PyMuPDF for text extraction (good CJK support) and pdfplumber
    for table detection and structured extraction.
    
    Args:
        file_path: Absolute path to the PDF file.
        
    Returns:
        ParsedDocument with page-by-page content.
        
    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file is not a valid PDF.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"PDF file not found: {file_path}")

    filename = os.path.basename(file_path)
    pages: list[PageContent] = []
    effective_ocr_provider = ocr_provider if ocr_provider is not None else settings.ocr_provider
    effective_ocr_dpi = ocr_dpi if ocr_dpi is not None else settings.ocr_dpi

    # Open with both libraries
    fitz_doc = fitz.open(file_path)
    plumber_doc = pdfplumber.open(file_path)

    try:
        total_pages = len(fitz_doc)

        if progress_callback is not None:
            progress_callback(
                ParseProgress(
                    stage="parsing",
                    total_pages=total_pages,
                    processed_pages=0,
                )
            )

        for i in range(total_pages):
            fitz_page = fitz_doc[i]
            plumber_page = plumber_doc.pages[i]
            page_num = i + 1  # 1-indexed

            page_content = _extract_native_page_content(fitz_page, plumber_page, page_num)
            pages.append(page_content)
            if progress_callback is not None:
                progress_callback(
                    ParseProgress(
                        stage="parsing",
                        total_pages=total_pages,
                        processed_pages=page_num,
                        current_page=page_num,
                    )
                )

        low_quality_page_indexes = [
            index
            for index, page in enumerate(pages)
            if page.diagnostics and page.diagnostics.is_low_quality
        ]

        normalized_provider = effective_ocr_provider.strip().lower()
        ocr_enabled = normalized_provider not in ("", "none", "off", "disabled")
        if ocr_enabled and low_quality_page_indexes:
            total_candidates = len(low_quality_page_indexes)
            if progress_callback is not None:
                progress_callback(
                    ParseProgress(
                        stage="ocr",
                        total_pages=total_pages,
                        processed_pages=0,
                        current_page=pages[low_quality_page_indexes[0]].page_num,
                        ocr_candidate_pages_total=total_candidates,
                        ocr_processed_pages=0,
                    )
                )

            ocr_processed_pages = 0
            for index in low_quality_page_indexes:
                page_content = pages[index]
                diagnostics = page_content.diagnostics
                if diagnostics is None:
                    continue

                ocr_text = _maybe_ocr_page(
                    fitz_doc[index],
                    diagnostics,
                    effective_ocr_provider,
                    effective_ocr_dpi,
                )
                if ocr_text:
                    if diagnostics.text_length < 80 or diagnostics.cjk_chars == 0:
                        page_content.text = ocr_text
                        page_content.extraction_method = "ocr"
                    else:
                        page_content.text = f"{page_content.text}\n\n[OCR fallback]\n{ocr_text}"
                        page_content.extraction_method = "native+ocr"

                ocr_processed_pages += 1
                if progress_callback is not None:
                    progress_callback(
                        ParseProgress(
                            stage="ocr",
                            total_pages=total_pages,
                            processed_pages=ocr_processed_pages,
                            current_page=page_content.page_num,
                            ocr_candidate_pages_total=total_candidates,
                            ocr_processed_pages=ocr_processed_pages,
                        )
                    )

    finally:
        fitz_doc.close()
        plumber_doc.close()

    return ParsedDocument(filename=filename, total_pages=total_pages, pages=pages)
