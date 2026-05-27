"""
Author: sizhchan
Org: dgaudit
Version: v0.1
Date: 2026-05-27
"""

"""
Determine page type for PDF processing pipeline.

Classifies each PDF page as one of:
  - electronic: has a usable text layer (e.g. Word-exported PDF)
  - scanned: pure image, no text layer (e.g. scanned document)
  - dual_layer: has both text and embedded images (needs cross-checking)
"""

import logging

import fitz

logger = logging.getLogger(__name__)


# Minimum character count for a page to be considered "with text layer"
MIN_TEXT_CHARS = 5

# Minimum ratio of CJK/non-glyph chars to detect text quality
MIN_VALID_CHAR_RATIO = 0.3


def classify_page(page: fitz.Page) -> str:
    """
    Classify a PDF page as 'electronic', 'scanned', or 'dual_layer'.

    Args:
        page: PyMuPDF Page object.

    Returns:
        One of 'electronic', 'scanned', 'dual_layer'.
    """
    text = page.get_text("text")
    text_len = len(text.strip())
    images = page.get_images(full=True)
    image_count = len(images)

    # Case 1: No text layer at all -> scanned
    if text_len < MIN_TEXT_CHARS:
        logger.debug("Page %d: scanned (text too short: %d chars)", page.number + 1, text_len)
        return "scanned"

    # Case 2: Has text but no embedded images -> pure electronic
    if image_count == 0:
        logger.debug("Page %d: electronic (text=%d chars, no images)", page.number + 1, text_len)
        return "electronic"

    # Case 3: Has both text and images -> dual layer, need quality check
    # Check if text is likely valid (not garbled/zero-width/glyph-only)
    valid_ratio = _calc_valid_text_ratio(text)
    if valid_ratio < MIN_VALID_CHAR_RATIO:
        logger.debug(
            "Page %d: dual_layer -> scanned fallback (valid_ratio=%.2f)",
            page.number + 1, valid_ratio,
        )
        return "scanned"

    logger.debug(
        "Page %d: dual_layer (text=%d chars, images=%d, valid_ratio=%.2f)",
        page.number + 1, text_len, image_count, valid_ratio,
    )
    return "dual_layer"


def _calc_valid_text_ratio(text: str) -> float:
    """
    Estimate the ratio of valid (readable) characters in extracted text.

    Filters out common zero-width, control, and private-use Unicode characters
    that indicate corrupted or garbled text layers.
    """
    if not text:
        return 0.0

    total = len(text)
    # Count valid chars: excludes control chars, private use area, surrogate pairs
    valid = 0
    for ch in text:
        code = ord(ch)
        # Exclude: control chars (0-31, 127-159), private use (E000-F8FF, F0000-FFFFD, 100000-10FFFD)
        if code <= 31:
            continue
        if 127 <= code <= 159:
            continue
        if 0xE000 <= code <= 0xF8FF:
            continue
        if 0xF0000 <= code <= 0xFFFFD:
            continue
        if 0x100000 <= code <= 0x10FFFD:
            continue
        valid += 1

    return valid / total if total > 0 else 0.0
