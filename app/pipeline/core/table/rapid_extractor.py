"""
Author: sizhchan
Org: dgaudit
Version: v0.1
Date: 2026-05-27
"""

"""
Table extraction using RapidTable (SLANet ONNX model).

Replaces the OpenCV line-detection approach with deep-learning-based
table structure recognition. RapidTable detects cell boundaries and
extracts text via its built-in RapidOCR engine.

Provides better accuracy for:
  - Borderless tables (text-only alignment)
  - Merged cells with complex spanning
  - Tables on noisy scanned backgrounds
"""

import logging
import os

logger = logging.getLogger(__name__)


def extract_table_with_rapid_table(
    roi_image, page_num: int, table_idx: int, output_dir: str
):
    """
    Run RapidTable on a cropped table region and return TableData.

    Args:
        roi_image: BGR numpy array of the cropped table region.
        page_num: 1-based page number.
        table_idx: 0-based table index on this page.
        output_dir: Directory for temp files.

    Returns:
        TableData or None if extraction fails.
    """
    import cv2
    from app.pipeline.ir.types import TableData, TableCell

    if roi_image.size == 0 or roi_image.shape[0] < 20 or roi_image.shape[1] < 20:
        return None

    roi_path = os.path.join(output_dir, f"_rt_p{page_num}_t{table_idx}.png")
    cv2.imwrite(roi_path, roi_image)

    try:
        from rapid_table import RapidTable
        rt = RapidTable()
        result = rt(roi_path)
    except ImportError:
        logger.warning("rapid_table not installed — install with: pip install rapid_table rapidocr")
        return None
    except Exception as exc:
        logger.warning("rapid_table inference failed: %s", exc)
        return None

    if not result or not result.pred_htmls or len(result.pred_htmls) == 0:
        return None

    # Parse HTML output to rows/cells
    html = result.pred_htmls[0]
    rows = _parse_table_html(html)
    if not rows or not is_valid_table(rows):
        return None

    max_cols = max(len(r) for r in rows)
    tdata_rows = []
    for r_idx, row_texts in enumerate(rows):
        while len(row_texts) < max_cols:
            row_texts.append("")
        cells = [TableCell(row=r_idx, col=c, text=t)
                 for c, t in enumerate(row_texts[:max_cols])]
        tdata_rows.append(cells)

    sheet_name = f"第{page_num}页_表格{table_idx+1}"
    return TableData(rows=tdata_rows, title="", sheet_name=sheet_name)


def _parse_table_html(html: str) -> list[list[str]]:
    """Parse a <table> HTML string into list of rows, each a list of cell texts."""
    from html.parser import HTMLParser

    class TableParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.rows = []
            self._current_row = []
            self._current_text = ""
            self._in_td = False

        def handle_starttag(self, tag, attrs):
            if tag == "tr":
                self._current_row = []
            elif tag in ("td", "th"):
                self._current_text = ""
                self._in_td = True

        def handle_endtag(self, tag):
            if tag in ("td", "th"):
                self._in_td = False
                self._current_row.append(self._current_text.strip())
            elif tag == "tr":
                if self._current_row:
                    self.rows.append(self._current_row)

        def handle_data(self, data):
            if self._in_td:
                self._current_text += data

    parser = TableParser()
    parser.feed(html)
    return parser.rows


def is_valid_table(rows: list[list[str]], min_rows: int = 3, min_cols: int = 2,
                   min_fill_ratio: float = 0.15) -> bool:
    """Filter out false table detections (text fragments misidentified as tables).

    Args:
        rows: Parsed table rows, each a list of cell texts.
        min_rows: Minimum number of rows required.
        min_cols: Minimum number of columns required.
        min_fill_ratio: Minimum ratio of non-empty cells to total cells.

    Returns:
        True if the table appears valid, False if it's likely a false positive.
    """
    if not rows or len(rows) < min_rows:
        return False
    max_cols = max(len(r) for r in rows) if rows else 0
    if max_cols < min_cols:
        return False
    # Count non-empty cells
    total = sum(len(r) for r in rows)
    non_empty = sum(1 for r in rows for c in r if c.strip())
    if total == 0 or non_empty / total < min_fill_ratio:
        return False
    return True

