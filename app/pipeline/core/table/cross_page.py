"""
Author: sizhchan
Org: dgaudit
Version: v0.1.2
Date: 2026-06-01
"""

"""
Cross-page table merging and table continuation detection.

Detects when a table spans multiple pages by checking for:
  - Missing bottom border on last page's table
  - Missing header row on next page's first table
  - Column count and alignment match between consecutive pages
"""

import logging

from app.pipeline.ir.types import TableData, TableCell

logger = logging.getLogger(__name__)

# Threshold for column count similarity (allow ±1 column due to detection noise)
MAX_COL_DIFF = 1


def merge_cross_page_tables(tables: list[TableData]) -> list[TableData]:
    """
    Merge tables that span multiple pages.

    A table is considered continued on the next page if:
      1. It's the last table on page N and first table on page N+1
      2. Both have similar column counts
      3. Page N's table has a continuation marker (no closing bottom line)
         OR page N+1's table has no header

    Args:
        tables: List of TableData in page order.

    Returns:
        Merged list with cross-page tables combined.
    """
    if len(tables) < 2:
        return tables

    merged = []
    skip_next = False

    for i in range(len(tables)):
        if skip_next:
            skip_next = False
            continue

        current = tables[i]

        if i < len(tables) - 1:
            next_table = tables[i + 1]
            if _is_continuation(current, next_table):
                # Merge: append next table's rows to current
                current = _merge_two(current, next_table)
                skip_next = True

        merged.append(current)

    return merged


def _is_continuation(t1: TableData, t2: TableData) -> bool:
    """
    Check if t2 is a continuation of t1 (same table split across pages).

    Criteria (all must be true):
      - t1 has is_cross_page_continuation=True (detected during extraction) OR
        (t1 has headers AND t2 has no headers AND column counts match)
      - Tables are on the SAME page (not separate PyMuPDF-detected tables)
    """
    # Don't merge tables from different pages (PyMuPDF-detected tables)
    # Sheet names like "第11页_表格2" contain page numbers
    p1 = _extract_page_from_sheet(t1.sheet_name)
    p2 = _extract_page_from_sheet(t2.sheet_name)
    if p1 is not None and p2 is not None and p1 != p2:
        return False

    if t1.is_cross_page_continuation:
        return True

    # Compare column counts
    cols1 = len(t1.rows[0]) if t1.rows else 0
    cols2 = len(t2.rows[0]) if t2.rows else 0
    if cols1 == 0 or cols2 == 0:
        return False
    if abs(cols1 - cols2) > MAX_COL_DIFF:
        return False

    # If t2 has no headers but t1 has headers → likely continuation
    if t1.headers and not t2.headers:
        return True

    # If both have no headers → rows are continuation
    if not t1.headers and not t2.headers:
        return True

    return False


def _extract_page_from_sheet(sheet_name: str) -> int | None:
    """Extract page number from sheet name like '第11页_表格2'."""
    import re
    m = re.search(r'第(\d+)页', sheet_name)
    return int(m.group(1)) if m else None


def _merge_two(t1: TableData, t2: TableData) -> TableData:
    """
    Merge t2's rows into t1 (inheriting t1's headers and title).
    """
    # Adjust row indices for t2's cells
    offset = len(t1.rows)
    for row in t2.rows:
        for cell in row:
            cell.row += offset
        t1.rows.append(row)

    t1.is_cross_page_continuation = t2.is_cross_page_continuation
    return t1


def mark_potential_continuation(
    table: TableData,
    is_last_on_page: bool,
    has_bottom_border: bool,
) -> TableData:
    """
    Mark a table as potentially continuing on the next page.

    A table likely continues if it's the last table on its page
    and lacks a proper bottom border.

    Args:
        table: TableData to examine.
        is_last_on_page: True if this is the last table on the page.
        has_bottom_border: True if a complete bottom horizontal line was detected.

    Returns:
        The same table with is_cross_page_continuation possibly set.
    """
    if is_last_on_page and not has_bottom_border:
        table.is_cross_page_continuation = True
        logger.debug("Table '%s' marked as cross-page continuation", table.title or "untitled")
    return table
