"""
Author: sizhchan
Org: dgaudit
Version: v0.2
Date: 2026-05-28
"""

"""
Red-header document enhancement for Chinese government documents.

Handles:
  1. Red text contrast boost for scanned documents
  2. Red horizontal line detection at page top/bottom
"""

import logging
import cv2
import numpy as np

logger = logging.getLogger(__name__)

RED_LOW_1 = np.array([0, 50, 50])
RED_HIGH_1 = np.array([10, 255, 255])
RED_LOW_2 = np.array([160, 50, 50])
RED_HIGH_2 = np.array([180, 255, 255])


def enhance_red_text(image: np.ndarray) -> np.ndarray:
    """Boost red region contrast for better OCR on red headers."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask1 = cv2.inRange(hsv, RED_LOW_1, RED_HIGH_1)
    mask2 = cv2.inRange(hsv, RED_LOW_2, RED_HIGH_2)
    red_mask = cv2.bitwise_or(mask1, mask2)
    red_mask = cv2.dilate(red_mask, np.ones((3,3),np.uint8), iterations=1)

    red_pct = cv2.countNonZero(red_mask) / (image.shape[0]*image.shape[1])
    if red_pct < 0.001:
        return image

    logger.info("Red header detected (%.1f%%) - enhancing", red_pct*100)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    enhanced = gray.copy()
    enhanced[red_mask > 0] = np.clip(gray[red_mask>0].astype(np.int16)*0.3, 0, 255).astype(np.uint8)
    enhanced_bgr = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
    result = image.copy()
    result[red_mask > 0] = enhanced_bgr[red_mask > 0]
    return result


def has_red_header(image: np.ndarray) -> bool:
    """Quick check: does this page have significant red content?"""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask1 = cv2.inRange(hsv, RED_LOW_1, RED_HIGH_1)
    mask2 = cv2.inRange(hsv, RED_LOW_2, RED_HIGH_2)
    red_mask = cv2.bitwise_or(mask1, mask2)
    red_pct = cv2.countNonZero(red_mask) / (image.shape[0]*image.shape[1])
    return red_pct > 0.001
