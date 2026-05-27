"""
Author: sizhchan
Org: dgaudit
Version: v0.1
Date: 2026-05-27
"""

"""
Image extraction: crop and save detected stamps and photos from document pages.

Returns position-aware results so the pipeline can create IR PageElements
with correct bbox for Word placement.

Each extracted image carries:
  - file_path: Saved PNG location
  - bbox: Original (x, y, w, h) in page-image coordinates (pixels)
  - element_type: "stamp" or "photo" for IR classification
"""

import logging
import os
from dataclasses import dataclass

import cv2

from app.pipeline.core.layout.stamp_detector import StampRegion, detect_all_stamps

logger = logging.getLogger(__name__)


@dataclass
class ExtractedImage:
    """An image extracted from a page, with position for IR placement."""
    file_path: str                          # Path to saved PNG
    bbox: tuple[int, int, int, int]         # (x, y, w, h) in page-image pixels
    element_type: str                       # "stamp" or "photo"
    confidence: float = 1.0                 # Detection confidence (for stamps)


def extract_stamps(
    image: 'np.ndarray',
    page_num: int,
    output_dir: str,
) -> list[ExtractedImage]:
    """
    Detect and save stamp regions from a page image.

    Args:
        image: BGR page image (numpy array).
        page_num: 1-based page number (for file naming).
        output_dir: Base directory for output files.

    Returns:
        List of ExtractedImage with bbox for IR placement.
    """
    import numpy as np

    stamps = detect_all_stamps(image)
    if not stamps:
        return []

    stamp_dir = os.path.join(output_dir, "images", "stamps")
    os.makedirs(stamp_dir, exist_ok=True)

    results = []
    for i, stamp in enumerate(stamps):
        cropped = _crop_region(image, stamp.bbox, padding=8)
        filename = f"page{page_num:04d}_stamp{i+1:02d}.png"
        filepath = os.path.join(stamp_dir, filename)
        cv2.imwrite(filepath, cropped)

        results.append(ExtractedImage(
            file_path=filepath,
            bbox=stamp.bbox,
            element_type="stamp",
            confidence=stamp.confidence,
        ))
        logger.debug(
            "Stamp saved: %s (color=%s, conf=%.2f, bbox=%s)",
            filename, stamp.color, stamp.confidence, stamp.bbox,
        )

    return results


def extract_photos(
    image: 'np.ndarray',
    page_num: int,
    output_dir: str,
    photo_bboxes: list[tuple[int, int, int, int]] | None = None,
) -> list[ExtractedImage]:
    """
    Save photo regions from a page image.

    Photo regions should be provided from layout analysis (YOLO or MinerU).
    If not provided, no extraction is performed.

    Args:
        image: BGR page image.
        page_num: 1-based page number.
        output_dir: Base output directory.
        photo_bboxes: List of (x, y, w, h) bounding boxes for photo regions.

    Returns:
        List of ExtractedImage with bbox for IR placement.
    """
    if not photo_bboxes:
        return []

    photo_dir = os.path.join(output_dir, "images", "photos")
    os.makedirs(photo_dir, exist_ok=True)

    results = []
    for i, bbox in enumerate(photo_bboxes):
        cropped = _crop_region(image, bbox, padding=5)
        filename = f"page{page_num:04d}_photo{i+1:02d}.png"
        filepath = os.path.join(photo_dir, filename)
        cv2.imwrite(filepath, cropped)

        results.append(ExtractedImage(
            file_path=filepath,
            bbox=bbox,
            element_type="photo",
        ))

    return results


def extracted_to_page_element(
    extracted: ExtractedImage,
    dpi: int = 250,
) -> 'PageElement':
    """
    Convert an ExtractedImage to a PageElement for IR insertion.

    Converts pixel coordinates to points (1pt = 1/72 inch) based on DPI.

    Args:
        extracted: ExtractedImage from extract_stamps/extract_photos.
        dpi: The DPI used when rendering the page to image.

    Returns:
        PageElement with type IMAGE or STAMP, correct bbox in points,
        and image_path set to the saved file.
    """
    from app.pipeline.ir.types import PageElement, ElementType

    px, py, pw, ph = extracted.bbox
    scale = 72.0 / dpi

    elem_type = ElementType.STAMP if extracted.element_type == "stamp" else ElementType.IMAGE

    return PageElement(
        type=elem_type,
        bbox=(int(px * scale), int(py * scale), int(pw * scale), int(ph * scale)),
        image_path=extracted.file_path,
    )


def _crop_region(
    image: 'np.ndarray',
    bbox: tuple[int, int, int, int],
    padding: int = 0,
) -> 'np.ndarray':
    """Crop a region from an image with optional padding."""
    import numpy as np
    x, y, w, h = bbox
    x1 = max(0, x - padding)
    y1 = max(0, y - padding)
    x2 = min(image.shape[1], x + w + padding)
    y2 = min(image.shape[0], y + h + padding)
    return image[y1:y2, x1:x2].copy()
