"""
Author: sizhchan
Org: dgaudit
Version: v0.1
Date: 2026-05-27
"""

"""
Build IR (Intermediate Representation) from raw OCR extraction results.

Converts PaddleOCR 3.5 predict() output into PageLayout with:
  - Font size estimation from character bounding box height
  - Paragraph grouping: adjacent text lines within the same Y-band
    are merged into one paragraph (preserves original reading flow)
  - Alignment detection: left / center / right based on X position
  - Bold detection heuristic from character width ratio
"""

import logging

from app.pipeline.ir.types import (
    ElementType,
    PageElement,
    PageLayout,
    PageSource,
    TextSpan,
    FontStyle,
)

logger = logging.getLogger(__name__)

# ── Font size estimation ──
# Character height in pixels to point size conversion:
#   pt ≈ pixel_height * 72 / DPI / 1.2
# The 1.2 factor accounts for line spacing (text line height > font size).
LINE_HEIGHT_RATIO = 1.2

# ── Paragraph grouping ──
# Maximum Y gap between consecutive text lines to consider them
# part of the same paragraph (in pixels, relative to line height).
PARAGRAPH_GAP_RATIO = 2.5  # Gap > 2.5x line height → new paragraph

# ── Alignment ──
# X position as fraction of page width.
LEFT_THRESHOLD = 0.15       # x/w < 0.15 → left-aligned
RIGHT_THRESHOLD = 0.70      # x/w > 0.70 → right-aligned
CENTER_TOLERANCE = 0.10     # abs(x/w - 0.5) < 0.10 → centered

# ── Bold detection ──
# If average character width > 1.3x the median character width,
# the text is likely bold.
BOLD_WIDTH_RATIO = 1.3

# Minimum number of characters to confidently detect bold
MIN_CHARS_FOR_BOLD = 4


def build_page_from_ocr_result(
    page_num: int,
    width: int,
    height: int,
    source: PageSource,
    ocr_page_result,       # paddlex OCRResult for one page
    dpi: int = 250,
) -> PageLayout:
    """
    Build a PageLayout from a single page's PaddleOCR 3.5 result.

    Enhances raw OCR output with:
      - Font size estimation (pt from bbox height / DPI)
      - Paragraph grouping (adjacent lines → single paragraph)
      - Alignment detection (left/center/right)
      - Bold detection (character width ratio)

    Args:
        page_num: 1-based page number.
        width: Page width in points.
        height: Page height in points.
        source: How the page was processed.
        ocr_page_result: Single OCRResult from ocr.predict().
        dpi: DPI used for rendering (for pt conversion).

    Returns:
        PageLayout with enhanced paragraph elements.
    """
    elements: list[PageElement] = []

    # Extract raw OCR data
    rec_texts = ocr_page_result.get("rec_texts", []) if hasattr(ocr_page_result, 'get') else (getattr(ocr_page_result, "rec_texts", []) or [])
    rec_scores = ocr_page_result.get("rec_scores", []) if hasattr(ocr_page_result, 'get') else (getattr(ocr_page_result, "rec_scores", []) or [])
    rec_polys = ocr_page_result.get("rec_polys", []) if hasattr(ocr_page_result, 'get') else (getattr(ocr_page_result, "rec_polys", []) or [])
    dt_polys = ocr_page_result.get("dt_polys", []) if hasattr(ocr_page_result, 'get') else (getattr(ocr_page_result, "dt_polys", []) or [])

    polys = dt_polys if dt_polys else rec_polys

    # Step 1: Build raw text spans with estimated formatting
    raw_spans: list[dict] = []  # [{span, x, y, w, h}]

    for i, text in enumerate(rec_texts):
        if not text or not text.strip():
            continue

        confidence = rec_scores[i] if i < len(rec_scores) else 0.0

        # Calculate bounding box
        if i < len(polys) and len(polys[i]) >= 4:
            poly = polys[i]
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            x = int(min(xs))
            y = int(min(ys))
            pw = int(max(xs) - x)
            ph = int(max(ys) - y)
        else:
            x, y, pw, ph = 0, 0, width, 20

        # Estimate font size in points
        font_size_pt = _estimate_font_size(ph, dpi)

        # Detect alignment
        alignment = _detect_alignment(x, width, dpi)

        # Detect bold
        is_bold = _detect_bold(text, pw, ph)

        span = TextSpan(
            text=text.strip(),
            font_size=font_size_pt,
            confidence=round(float(confidence), 4),
            is_bold=is_bold,
        )
        raw_spans.append({
            "span": span,
            "x": x,
            "y": y,
            "w": pw,
            "h": ph,
            "alignment": alignment,
        })

    if not raw_spans:
        return PageLayout(
            page_num=page_num, width=width, height=height,
            source=source, elements=[], reading_order=[],
        )

    # Step 2: Sort by Y (top-to-bottom), then X (left-to-right)
    raw_spans.sort(key=lambda s: (s["y"], s["x"]))

    # Step 3: Group into paragraphs
    elements = _group_into_paragraphs(raw_spans)

    # Reading order follows paragraph order (already sorted)
    reading_order = list(range(len(elements)))

    return PageLayout(
        page_num=page_num,
        width=width,
        height=height,
        source=source,
        elements=elements,
        reading_order=reading_order,
    )


def _estimate_font_size(bbox_height_px: int, dpi: int) -> int:
    """Estimate font size in points from bounding box height."""
    if bbox_height_px <= 0:
        return 12
    pt = bbox_height_px * 72.0 / dpi / LINE_HEIGHT_RATIO
    return max(6, min(72, round(pt)))


def _detect_alignment(x_px: int, page_width_pt: int, dpi: int) -> str:
    """Detect text alignment from X position relative to page width."""
    page_width_px = page_width_pt * dpi / 72.0
    if page_width_px <= 0:
        return "left"
    ratio = x_px / page_width_px
    if ratio < LEFT_THRESHOLD:
        return "left"
    if ratio > RIGHT_THRESHOLD:
        return "right"
    if abs(ratio - 0.5) < CENTER_TOLERANCE:
        return "center"
    return "left"


def _detect_bold(text: str, bbox_w: int, bbox_h: int) -> bool:
    """Heuristic bold detection based on character width-to-height ratio."""
    if len(text) < MIN_CHARS_FOR_BOLD or bbox_h <= 0:
        return False
    # Average character width
    avg_char_w = bbox_w / len(text)
    # CJK characters are roughly square (w ≈ h); bold text is wider
    ratio = avg_char_w / bbox_h
    return ratio > 1.25


def _group_into_paragraphs(raw_spans: list[dict]) -> list[PageElement]:
    """
    Group adjacent text lines into paragraphs.

    Lines are merged into the same paragraph if:
      - Y gap between consecutive lines ≤ 2.5× average line height
      - They share the same alignment
      - They share similar font size (±2pt)
    """
    if not raw_spans:
        return []

    paragraphs: list[PageElement] = []
    current_group: list[dict] = [raw_spans[0]]

    for i in range(1, len(raw_spans)):
        prev = current_group[-1]
        curr = raw_spans[i]

        prev_y_end = prev["y"] + prev["h"]
        curr_y = curr["y"]
        gap = curr_y - prev_y_end

        # Average line height in the current group
        avg_h = sum(s["h"] for s in current_group) / len(current_group)

        # Decision: same paragraph?
        same_para = True

        # Check Y gap
        if gap > avg_h * PARAGRAPH_GAP_RATIO:
            same_para = False

        # Check alignment consistency
        if prev.get("alignment") != curr.get("alignment"):
            same_para = False

        # Check font size consistency (±3pt tolerance for paragraph mixing)
        prev_size = prev["span"].font_size or 12
        curr_size = curr["span"].font_size or 12
        if abs(prev_size - curr_size) > 3:
            same_para = False

        if same_para:
            current_group.append(curr)
        else:
            # Close current paragraph
            paragraphs.append(_make_paragraph(current_group))
            current_group = [curr]

    # Close last paragraph
    if current_group:
        paragraphs.append(_make_paragraph(current_group))

    return paragraphs


def _make_paragraph(group: list[dict]) -> PageElement:
    """Merge a group of adjacent text spans into one paragraph element."""
    # Collect all spans in order
    spans = [s["span"] for s in group]

    # Paragraph bbox: union of all span bboxes
    xs = [s["x"] for s in group]
    ys = [s["y"] for s in group]
    x = min(xs)
    y = min(ys)
    w = max(s["x"] + s["w"] for s in group) - x
    h = max(s["y"] + s["h"] for s in group) - y

    return PageElement(
        type=ElementType.PARAGRAPH,
        bbox=(x, y, w, h),
        content=spans,
    )
