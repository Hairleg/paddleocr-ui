"""
Author: sizhchan
Org: dgaudit
Version: v0.1.2
Date: 2026-06-01
"""

"""
Intermediate Representation types for document processing pipeline.

These dataclasses represent the parsed structure of a document page
and the complete document, serving as the bridge between OCR/extraction
modules and the export/generation modules.
"""

from dataclasses import dataclass, field
from enum import Enum


class ElementType(str, Enum):
    """Types of elements that can appear on a page."""
    PARAGRAPH = "paragraph"
    TABLE = "table"
    IMAGE = "image"
    STAMP = "stamp"
    FORMULA = "formula"


class PageSource(str, Enum):
    """How a page was processed."""
    ELECTRONIC = "electronic"   # Has text layer, MinerU handles structure
    SCANNED = "scanned"         # Pure image, PaddleOCR handles everything
    DUAL_LAYER = "dual_layer"   # Both text and image layers present


class FontStyle(str, Enum):
    """Basic font style classification."""
    NORMAL = "normal"
    BOLD = "bold"


@dataclass
class TextSpan:
    """A single contiguous run of text with formatting metadata."""
    text: str
    font_size: int | None = None       # Point size (e.g. 12)
    font_name: str | None = None       # e.g. "SimSun", "SimHei"
    is_bold: bool = False
    color: str = "#000000"             # Hex color from PDF text layer
    confidence: float = 0.0            # OCR confidence 0.0-1.0


@dataclass
class TableCell:
    """A single cell within a reconstructed table."""
    row: int
    col: int
    rowspan: int = 1
    colspan: int = 1
    text: str = ""


@dataclass
class TableData:
    """Complete table data, ready for Excel/Word export."""
    title: str = ""                     # Table title extracted from above the table
    sheet_name: str = ""                # Name for Excel sheet tab
    headers: list[str] = field(default_factory=list)   # Column headers
    rows: list[list[TableCell]] = field(default_factory=list)  # Data cells
    has_merged_cells: bool = False
    is_cross_page_continuation: bool = False  # This table continues from previous page


@dataclass
class PageElement:
    """Any element detected on a page: paragraph, table, image, stamp, or formula."""
    type: ElementType
    bbox: tuple[int, int, int, int]  # (x, y, w, h) in points
    content: list[TextSpan] | list[list[TableCell]] | str | None = None
    image_path: str | None = None     # Local path to cropped PNG (images/stamps)
    latex: str | None = None          # LaTeX source (formulas only)


@dataclass
class PageLayout:
    """All elements on a single page, with reading order."""
    page_num: int                     # 1-based
    width: int                        # Page width in points
    height: int                       # Page height in points
    source: PageSource                # How this page was processed
    elements: list[PageElement] = field(default_factory=list)
    reading_order: list[int] = field(default_factory=list)  # Indices into elements


@dataclass
class DocumentLayout:
    """Complete document structure ready for export."""
    pages: list[PageLayout] = field(default_factory=list)
    tables: list[TableData] = field(default_factory=list)  # All tables (cross-page merged)
    stamp_paths: list[str] = field(default_factory=list)   # Paths to stamp PNGs
    photo_paths: list[str] = field(default_factory=list)   # Paths to photo PNGs
