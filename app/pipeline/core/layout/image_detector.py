"""
Author: sizhchan
Org: dgaudit
Version: v0.1
Date: 2026-05-27
"""


"""
Image region detection and extraction for scanned document pages.

Controlled by the `image_level` parameter:
  0: Disabled (text-only mode)
  1: Detect and crop image/photo regions, save as PNG
  2: Deep analysis — attempt OCR on image captions/labels (reserved)
"""

import logging
import os

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def detect_image_regions(img: np.ndarray, image_level: int = 0) -> list[dict]:
    """
    Detect image/photo/logo regions on a scanned page.

    Uses contour analysis and texture density to distinguish
    photos from text blocks. Only effective on scanned/image pages.

    Args:
        img: BGR page image.
        image_level: 0=skip, 1=basic, 2=deep.

    Returns:
        List of dicts with keys: bbox (x,y,w,h), area, confidence.
    """
    if image_level == 0:
        return []

    regions = []

    # Convert to grayscale and detect high-texture (photo-like) regions
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Adaptive threshold to separate content from background
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY_INV, 21, 10)

    # Find contours
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    img_area = img.shape[0] * img.shape[1]
    min_area = img_area * 0.002  # Minimum 0.2% of page

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue

        x, y, w, h = cv2.boundingRect(cnt)

        # Skip very thin/small regions (likely text lines)
        if h < 30 or w < 30:
            continue

        # Texture check: high std deviation = photo, low = text block
        roi = gray[max(0,y):min(img.shape[0],y+h), max(0,x):min(img.shape[1],x+w)]
        if roi.size == 0:
            continue
        texture = float(np.std(roi))

        # Photos have moderate texture; pure text blocks have extreme texture
        if image_level == 1 and texture < 30:
            continue  # Too uniform, likely empty space

        regions.append({
            "bbox": (x, y, w, h),
            "area": int(area),
            "texture": round(texture, 1),
        })

    # Sort by position (top-to-bottom, left-to-right)
    regions.sort(key=lambda r: (r["bbox"][1], r["bbox"][0]))

    if image_level >= 2:
        logger.info("Deep image analysis enabled (image_level=%d), found %d regions",
                     image_level, len(regions))

    return regions


def crop_and_save_images(img: np.ndarray, regions: list[dict],
                         output_dir: str, page_num: int, dpi: int) -> list[str]:
    """
    Crop detected image regions and save as PNG files.

    Returns list of saved file paths.
    """
    img_dir = os.path.join(output_dir, "images", "photos")
    os.makedirs(img_dir, exist_ok=True)

    saved = []
    for i, region in enumerate(regions[:50]):  # Max 50 images per page
        x, y, w, h = region["bbox"]
        # Add margin
        mx, my = max(0, x-5), max(0, y-5)
        mw, mh = min(img.shape[1]-mx, w+10), min(img.shape[0]-my, h+10)
        cropped = img[my:my+mh, mx:mx+mw]
        if cropped.size == 0:
            continue

        path = os.path.join(img_dir, f"page{page_num:04d}_img{i+1:02d}.png")
        cv2.imwrite(path, cropped)
        saved.append(path)

    return saved
