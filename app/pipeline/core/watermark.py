"""
Author: sizhchan
Org: dgaudit
Version: v0.2.0
Date: 2026-06-01
"""

"""
Watermark removal using HSV color space analysis.

Chinese bidding documents commonly feature watermarks such as:
  - Light gray diagonal "仅供XX投标使用" text
  - Semi-transparent overlay patterns
  - Light colored background logos

Strategy:
  1. Convert to HSV and detect low-saturation, high-value regions (typical gray watermark)
  2. Create a binary mask of watermark pixels
  3. Apply morphological closing to connect fragmented mask regions
  4. Use OpenCV inpainting (Telea / Navier-Stokes) to reconstruct watermarked areas
"""

import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Default HSV thresholds for gray/light watermarks
# Gray watermarks: low saturation, moderate-to-high value
DEFAULT_SATURATION_MAX = 60    # S channel upper bound (watermarks are desaturated)
DEFAULT_VALUE_MIN = 150        # V channel lower bound (watermarks are light)
DEFAULT_VALUE_MAX = 245        # V channel upper bound (exclude pure white paper)

# Morphology kernel size for mask cleanup
DEFAULT_MORPH_KERNEL = (5, 5)

# Inpainting radius (pixels around watermarked areas to use for reconstruction)
DEFAULT_INPAINT_RADIUS = 5


def remove_watermark(
    image: np.ndarray,
    saturation_max: int = DEFAULT_SATURATION_MAX,
    value_min: int = DEFAULT_VALUE_MIN,
    value_max: int = DEFAULT_VALUE_MAX,
    morph_kernel: tuple = DEFAULT_MORPH_KERNEL,
    inpaint_radius: int = DEFAULT_INPAINT_RADIUS,
) -> np.ndarray:
    """
    Detect and remove watermark from a document image.

    Args:
        image: BGR image as numpy array (H, W, 3).
        saturation_max: Maximum saturation value for watermark pixels (0-255).
            Lower values are more selective (only catch very gray watermarks).
        value_min: Minimum brightness value for watermark pixels (0-255).
        value_max: Maximum brightness value for watermark pixels (0-255).
            Pixels brighter than this (near white) are excluded.
        morph_kernel: (w, h) kernel size for morphological closing.
        inpaint_radius: Radius for OpenCV inpainting.

    Returns:
        Image with watermark removed (BGR, same shape as input).
    """
    # Step 1: Convert to HSV
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    # Step 2: Create watermark mask
    # Gray/light watermarks: low S, high V (but not pure white)
    mask = cv2.inRange(
        hsv,
        np.array([0, 0, value_min], dtype=np.uint8),
        np.array([180, saturation_max, value_max], dtype=np.uint8),
    )

    # Step 3: Clean up mask with morphological operations
    # Close small gaps in the watermark mask
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, morph_kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    # Remove tiny isolated noise pixels
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    # Step 4: Inpaint over the masked areas
    # INPAINT_TELEA is faster; INPAINT_NS is higher quality on thin lines
    result = cv2.inpaint(image, mask, inpaint_radius, cv2.INPAINT_TELEA)

    watermark_pct = (np.sum(mask > 0) / mask.size) * 100
    if watermark_pct > 0.1:
        logger.debug(
            "Watermark removed: %.1f%% of pixels affected", watermark_pct,
        )
    else:
        logger.debug("No significant watermark detected (%.2f%%)", watermark_pct)

    return result


def has_watermark(
    image: np.ndarray,
    saturation_max: int = DEFAULT_SATURATION_MAX,
    value_min: int = DEFAULT_VALUE_MIN,
    min_coverage_pct: float = 0.5,
) -> bool:
    """
    Quick check: does this page likely have a watermark?

    Args:
        image: BGR image.
        saturation_max: Max S value for watermark detection.
        value_min: Min V value for watermark detection.
        min_coverage_pct: Minimum percentage of pixels that must match
            the watermark profile to return True.

    Returns:
        True if watermark-like pixels exceed threshold.
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(
        hsv,
        np.array([0, 0, value_min], dtype=np.uint8),
        np.array([180, saturation_max, 255], dtype=np.uint8),
    )
    coverage = (np.sum(mask > 0) / mask.size) * 100
    return coverage >= min_coverage_pct


def estimate_watermark_params(
    image: np.ndarray,
) -> dict:
    """
    Analyze image to estimate optimal watermark detection parameters.
    Returns a dict with recommended saturation_max, value_min, etc.

    This is useful for auto-tuning on different document types.
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Analyze brightness distribution to find watermark plateau
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()

    # Find the background peak (typically around 200-250 for white paper)
    bg_peak = np.argmax(hist[128:]) + 128

    # Watermarks typically appear as a slight dip between the text peak (dark)
    # and the background peak (white)
    text_peak = np.argmax(hist[:bg_peak])

    return {
        "saturation_max": DEFAULT_SATURATION_MAX,
        "value_min": text_peak + 30,     # Slightly above text intensity
        "value_max": bg_peak - 20,        # Slightly below paper white
        "background_peak": int(bg_peak),
        "text_peak": int(text_peak),
    }
