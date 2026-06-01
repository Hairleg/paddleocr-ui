"""
Author: sizhchan
Org: dgaudit
Version: v0.1.2
Date: 2026-06-01
"""

"""
Table header and title separation.

Extracts table titles and column headers from OCR results
above and at the top of detected table regions.

Rules:
  - Text just above the table bounding box → table title
  - First row of text inside the table → column headers
  - If no clear separation, first row serves as both
"""

import logging
import re

from app.pipeline.ir.types import TextSpan

logger = logging.getLogger(__name__)

# Maximum Y-distance from table top to consider text as "title above"
TITLE_ABOVE_MARGIN = 60  # pixels

# Characters that commonly appear in table headers but not titles
HEADER_INDICATORS = re.compile(r'[序号|编号|名称|金额|数量|单位|备注|合计|序号]')


def separate_title_and_headers(
    table_bbox: tuple[int, int, int, int],
    page_texts: list[TextSpan],
    table_texts: list[TextSpan],
) -> tuple[str, list[str]]:
    """
    Separate table title and column headers from recognized text.

    Args:
        table_bbox: (x, y, w, h) of the detected table.
        page_texts: All text spans on the page (with bbox coordinates).
        table_texts: Text spans inside the table region.

    Returns:
        (title, headers): Table title string and list of header strings.
    """
    tx, ty, tw, th = table_bbox

    # Step 1: Find title text just above the table
    title_candidates = []
    for span in page_texts:
        # Text must be above the table, within margin
        span_y = getattr(span, 'y', 0)
        if ty - TITLE_ABOVE_MARGIN <= span_y <= ty:
            # Must be within horizontal range of the table
            if tx - 20 <= getattr(span, 'x', tx) <= tx + tw + 20:
                title_candidates.append(span.text)

    title = " ".join(title_candidates) if title_candidates else ""

    # Step 2: Identify column headers (first row of table text)
    if not table_texts:
        return title, []

    # Sort table texts by Y then X to get reading order
    sorted_texts = sorted(
        table_texts,
        key=lambda s: (getattr(s, 'y', 0), getattr(s, 'x', 0)),
    )

    # First row: texts at the same Y level (within tolerance)
    if not sorted_texts:
        return title, []

    first_y = getattr(sorted_texts[0], 'y', 0)
    Y_TOLERANCE = 10  # pixels tolerance for "same row"

    header_spans = []
    data_start_idx = 0
    for i, span in enumerate(sorted_texts):
        if abs(getattr(span, 'y', 0) - first_y) <= Y_TOLERANCE:
            header_spans.append(span)
            data_start_idx = i + 1
        else:
            break

    headers = [s.text for s in header_spans]

    # Step 3: If headers look like data (all numeric), they might not be headers
    if _all_numeric(headers):
        headers = []

    # Step 4: If no title but we have headers, first header candidate might be title
    if not title and headers:
        if _looks_like_title(headers[0]):
            title = headers[0]
            headers = headers[1:]

    return title, headers


def _all_numeric(texts: list[str]) -> bool:
    """Check if all texts appear to be numeric data rather than headers."""
    if not texts:
        return False
    numeric_count = sum(1 for t in texts if re.match(r'^[\d.,%\s]+$', t))
    return numeric_count == len(texts)


def _looks_like_title(text: str) -> bool:
    """Heuristic: does this text look like a table title rather than a column header?"""
    # Titles are typically longer and don't contain header indicator words
    if len(text) >= 10 and not HEADER_INDICATORS.search(text):
        return True
    # Chinese table titles often end with "表" or "清单" or contain special chars
    if any(kw in text for kw in ['表', '清单', '报价', '预算', '统计']):
        return True
    return False


def make_sheet_name(title: str, fallback: str = "") -> str:
    """
    Generate a clean Excel sheet name from a table title.
    Strips common table numbering prefixes like "表3-2" or "附表一".
    """
    if not title:
        return fallback

    # Remove common table number prefixes
    cleaned = re.sub(r'^[表附表][\d\-一二三四五六七八九十]+[\s\-]*', '', title)
    cleaned = re.sub(r'^[\d\.\s]+', '', cleaned)  # Leading numbers

    # Clean up whitespace
    cleaned = cleaned.strip()

    if not cleaned:
        return fallback

    # Truncate to Excel limit (31 chars)
    if len(cleaned) > 31:
        cleaned = cleaned[:28] + "..."

    return cleaned
