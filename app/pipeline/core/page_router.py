"""
Author: sizhchan
Org: dgaudit
Version: v0.1
Date: 2026-05-27
"""

"""Page classifier — identifies page type AND table presence."""

import logging
import fitz

logger = logging.getLogger(__name__)

MIN_TEXT_CHARS = 5
MIN_VALID_CHAR_RATIO = 0.3


def classify_page(page: fitz.Page) -> str:
    """Classify as 'electronic', 'scanned', or 'dual_layer'."""
    text = page.get_text("text")
    text_len = len(text.strip())
    images = page.get_images(full=True)
    image_count = len(images)

    if text_len < MIN_TEXT_CHARS:
        return "scanned"
    if image_count == 0:
        return "electronic"

    valid_ratio = _calc_valid_text_ratio(text)
    if valid_ratio < MIN_VALID_CHAR_RATIO:
        return "scanned"
    return "dual_layer"


def has_tables(page: fitz.Page) -> bool:
    """Quick pre-flight: does this page likely contain table structures?

    Uses PyMuPDF's fast table detection for electronic pages, and a
    low-resolution YOLO render for scanned pages. Returns False for
    pure text documents (red headers, letters, reports).
    """
    source = classify_page(page)

    if source == "electronic":
        # PyMuPDF find_tables is fast and reliable for electronic PDFs
        try:
            tabs = page.find_tables(strategy="lines")
            return bool(tabs and len(tabs.tables) > 0)
        except Exception:
            return False

    # Scanned/dual-layer: render thumbnail and check with YOLO
    try:
        pix = page.get_pixmap(dpi=72)  # Low res for speed
        import cv2, numpy as np
        img = cv2.imdecode(
            np.frombuffer(pix.tobytes("png"), np.uint8),
            cv2.IMREAD_COLOR
        )
        if img is None:
            return False

        from app.pipeline.core.layout.mineru_layout import detect_table_regions_yolo
        regions = detect_table_regions_yolo(img)
        if not regions:
            return False

        # Only count valid grid-like regions
        valid = 0
        for x, y, w, h in regions:
            if w > img.shape[1] * 0.15 and h > 30:
                valid += 1
        return valid > 0
    except Exception:
        # If YOLO unavailable, assume no tables (safe default for pure text)
        return False


def _calc_valid_text_ratio(text: str) -> float:
    if not text:
        return 0.0
    total = len(text)
    valid = 0
    for ch in text:
        code = ord(ch)
        if code <= 31: continue
        if 127 <= code <= 159: continue
        if 0xE000 <= code <= 0xF8FF: continue
        if 0xF0000 <= code <= 0xFFFFD: continue
        if 0x100000 <= code <= 0x10FFFD: continue
        valid += 1
    return valid / total if total > 0 else 0.0
