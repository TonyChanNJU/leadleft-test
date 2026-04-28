"""PDF parsing service using PyMuPDF for text and pdfplumber for tables.

Handles multi-column layouts, tables, and Chinese text. Outputs structured
page-by-page content with metadata for downstream indexing.
"""

import os
import re
from dataclasses import dataclass, field
from typing import Optional

import fitz  # PyMuPDF
import pdfplumber


@dataclass
class TableData:
    """Extracted table data with position info."""
    page_num: int
    bbox: tuple  # (x0, y0, x1, y1)
    markdown: str  # Table rendered as markdown


@dataclass
class PageContent:
    """Content extracted from a single PDF page."""
    page_num: int  # 1-indexed
    text: str
    tables: list[TableData] = field(default_factory=list)

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


def _extract_page_content(
    fitz_page: fitz.Page,
    plumber_page: pdfplumber.page.Page,
    page_num: int,
) -> PageContent:
    """Extract content from a single page, merging text and tables.
    
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

    return PageContent(page_num=page_num, text=merged_text, tables=tables)


def parse_pdf(file_path: str) -> ParsedDocument:
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

    # Open with both libraries
    fitz_doc = fitz.open(file_path)
    plumber_doc = pdfplumber.open(file_path)

    try:
        total_pages = len(fitz_doc)

        for i in range(total_pages):
            fitz_page = fitz_doc[i]
            plumber_page = plumber_doc.pages[i]
            page_num = i + 1  # 1-indexed

            page_content = _extract_page_content(fitz_page, plumber_page, page_num)
            pages.append(page_content)

    finally:
        fitz_doc.close()
        plumber_doc.close()

    return ParsedDocument(filename=filename, total_pages=total_pages, pages=pages)
