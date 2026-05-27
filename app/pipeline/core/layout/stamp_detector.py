"""
Author: sizhchan
Org: dgaudit
Version: v0.1
Date: 2026-05-27
"""

"""
Stamp (公章) detection using traditional computer vision.

Chinese official stamps (公章) have distinctive visual characteristics:
  - Red stamps: circular/elliptical, red hue (HSV H ~0-10 or 160-180),
    dense text texture inside, often on white/gray background
  - Blue stamps: same shape, blue hue (HSV H ~100-130)
  - Black/white circular stamps: grayscale, rely on shape + internal texture

Strategy:
  1. HSV filtering for red/blue candidates
  2. Morphological cleanup to connect stamp fragments
  3. Contour detection + ellipse fitting (minEnclosingCircle + aspect ratio check)
  4. Internal texture density check (Canny edges inside the region)
  5. Filter false positives: round logos, pie charts, circular borders
"""

import logging
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ── Red stamp HSV thresholds ──
# Two ranges because red wraps around 0/180 in OpenCV HSV
RED_HUE_LOW_1 = 0
RED_HUE_HIGH_1 = 10
RED_HUE_LOW_2 = 160
RED_HUE_HIGH_2 = 180
RED_SAT_MIN = 50       # Saturation: vivid red (>50)
RED_VAL_MIN = 30       # Value: not too dark

# ── Blue stamp HSV thresholds ──
BLUE_HUE_LOW = 100
BLUE_HUE_HIGH = 130
BLUE_SAT_MIN = 50
BLUE_VAL_MIN = 30

# ── Shape constraints ──
MIN_STAMP_RADIUS = 50      # Pixels, minimum stamp radius (raised from 30)
MAX_STAMP_RADIUS = 400     # Pixels, maximum stamp radius
MAX_ASPECT_RATIO = 1.3     # max(width/height) for elliptical stamps
MIN_ASPECT_RATIO = 0.77    # 1/1.3

# ── Texture check ──
# A stamp contains dense text. We check Canny edge density inside the region.
MIN_EDGE_DENSITY = 0.05    # Minimum ratio of edge pixels inside stamp bbox (raised from 0.03)
CANNY_LOW = 50
CANNY_HIGH = 150

# ── Morphological kernel for connecting stamp fragments ──
MORPH_CLOSE_KERNEL = (7, 7)

# ── Maximum stamps per page ──
# Real documents rarely have more than a handful of stamps.
# A single page should never have > 20 stamps.
MAX_STAMPS_PER_PAGE = 20


@dataclass
class StampRegion:
    """A detected stamp region with bounding box and confidence."""
    bbox: tuple[int, int, int, int]     # (x, y, w, h)
    center: tuple[int, int]             # (cx, cy)
    radius: int
    color: str                          # "red" | "blue" | "black"
    confidence: float                   # 0.0-1.0 combined score


def detect_red_stamps(
    image: np.ndarray,
    min_radius: int = MIN_STAMP_RADIUS,
    max_radius: int = MAX_STAMP_RADIUS,
) -> list[StampRegion]:
    """
    Detect red (or blue) stamps using HSV filtering + contour analysis.

    Args:
        image: BGR image.
        min_radius: Minimum stamp radius in pixels.
        max_radius: Maximum stamp radius in pixels.

    Returns:
        List of StampRegion objects sorted by confidence (highest first).
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    # Build red mask from two hue ranges
    mask1 = cv2.inRange(
        hsv,
        np.array([RED_HUE_LOW_1, RED_SAT_MIN, RED_VAL_MIN], dtype=np.uint8),
        np.array([RED_HUE_HIGH_1, 255, 255], dtype=np.uint8),
    )
    mask2 = cv2.inRange(
        hsv,
        np.array([RED_HUE_LOW_2, RED_SAT_MIN, RED_VAL_MIN], dtype=np.uint8),
        np.array([RED_HUE_HIGH_2, 255, 255], dtype=np.uint8),
    )
    red_mask = cv2.bitwise_or(mask1, mask2)

    # Also detect blue stamps
    blue_mask = cv2.inRange(
        hsv,
        np.array([BLUE_HUE_LOW, BLUE_SAT_MIN, BLUE_VAL_MIN], dtype=np.uint8),
        np.array([BLUE_HUE_HIGH, 255, 255], dtype=np.uint8),
    )

    stamps = []
    stamps.extend(_extract_stamps_from_mask(image, red_mask, "red", min_radius, max_radius))
    stamps.extend(_extract_stamps_from_mask(image, blue_mask, "blue", min_radius, max_radius))

    # Sort by confidence descending
    stamps.sort(key=lambda s: s.confidence, reverse=True)
    return stamps


def detect_black_white_circular_stamps(
    image: np.ndarray,
    min_radius: int = MIN_STAMP_RADIUS,
    max_radius: int = MAX_STAMP_RADIUS,
) -> list[StampRegion]:
    """
    Detect black-and-white circular stamps using Hough Circles.

    For documents where stamps appear in grayscale (scanned B/W documents),
    we use shape detection rather than color.

    Args:
        image: BGR image.
        min_radius: Minimum stamp radius.
        max_radius: Maximum stamp radius.

    Returns:
        List of StampRegion objects.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Gaussian blur to reduce noise before Hough detection
    blurred = cv2.GaussianBlur(gray, (9, 9), 2)

    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=min_radius * 2,
        param1=CANNY_HIGH,
        param2=80,          # Accumulator threshold: higher = fewer false circles
        minRadius=min_radius,
        maxRadius=max_radius,
    )

    stamps = []
    if circles is not None:
        circles = np.round(circles[0, :]).astype(int)
        for cx, cy, r in circles:
            # Check internal texture density to filter false positives
            x1 = max(0, cx - r)
            y1 = max(0, cy - r)
            x2 = min(image.shape[1], cx + r)
            y2 = min(image.shape[0], cy + r)
            roi = gray[y1:y2, x1:x2]

            if roi.size == 0:
                continue

            edge_density = _calc_edge_density(roi)
            if edge_density < MIN_EDGE_DENSITY:
                continue

            w = x2 - x1
            h = y2 - y1
            stamps.append(StampRegion(
                bbox=(x1, y1, w, h),
                center=(int(cx), int(cy)),
                radius=int(r),
                color="black",
                confidence=min(edge_density / 0.1, 1.0),
            ))

    stamps.sort(key=lambda s: s.confidence, reverse=True)
    return stamps


def detect_all_stamps(
    image: np.ndarray,
    min_radius: int = MIN_STAMP_RADIUS,
    max_radius: int = MAX_STAMP_RADIUS,
) -> list[StampRegion]:
    """
    Combine red/blue and black/white stamp detection.

    Returns deduplicated list of stamp regions sorted by confidence.
    """
    colored = detect_red_stamps(image, min_radius, max_radius)

    # B/W circular detection disabled by default — HoughCircles produces too many
    # false positives on document text layouts. Enable only for known B/W stamp use cases.
    # bw = detect_black_white_circular_stamps(image, min_radius, max_radius)

    all_stamps = list(colored)
    # for stamp in bw:
    #     if not _has_overlap(stamp, colored, iou_threshold=0.5):
    #         all_stamps.append(stamp)

    all_stamps.sort(key=lambda s: s.confidence, reverse=True)

    # Hard cap: never return more than MAX_STAMPS_PER_PAGE
    if len(all_stamps) > MAX_STAMPS_PER_PAGE:
        all_stamps = all_stamps[:MAX_STAMPS_PER_PAGE]

    return all_stamps


def crop_stamp(image: np.ndarray, stamp: StampRegion, padding: int = 10) -> np.ndarray:
    """
    Crop a stamp region from the image with optional padding.

    Returns the cropped BGR image slice.
    """
    x, y, w, h = stamp.bbox
    x1 = max(0, x - padding)
    y1 = max(0, y - padding)
    x2 = min(image.shape[1], x + w + padding)
    y2 = min(image.shape[0], y + h + padding)
    return image[y1:y2, x1:x2].copy()


# ── Internal helpers ──

def _extract_stamps_from_mask(
    image: np.ndarray,
    mask: np.ndarray,
    color: str,
    min_radius: int,
    max_radius: int,
) -> list[StampRegion]:
    """Extract stamp regions from a binary color mask."""
    # Morphological close to connect fragmented stamp fragments
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, MORPH_CLOSE_KERNEL)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    stamps = []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < np.pi * min_radius ** 2:
            continue

        # Fit ellipse to check circularity
        if len(contour) < 5:
            continue

        ellipse = cv2.fitEllipse(contour)
        (cx, cy), (major, minor), angle = ellipse

        # Aspect ratio check
        if major <= 0 or minor <= 0:
            continue
        aspect = max(major, minor) / min(major, minor)
        if aspect > MAX_ASPECT_RATIO:
            continue

        # Radius bounds
        avg_radius = (major + minor) / 4
        if avg_radius < min_radius or avg_radius > max_radius:
            continue

        # Internal texture check
        x, y, w, h = cv2.boundingRect(contour)
        roi = gray[y:y+h, x:x+w] if h > 0 and w > 0 else np.zeros((1, 1), dtype=np.uint8)
        edge_density = _calc_edge_density(roi)
        if edge_density < MIN_EDGE_DENSITY:
            continue

        confidence = min(edge_density / 0.1, 1.0)
        stamps.append(StampRegion(
            bbox=(x, y, w, h),
            center=(int(cx), int(cy)),
            radius=int(avg_radius),
            color=color,
            confidence=confidence,
        ))

    return stamps


def _calc_edge_density(roi: np.ndarray) -> float:
    """
    Calculate Canny edge pixel density in a region.
    Higher values indicate dense text typical of stamps.
    """
    if roi.size == 0:
        return 0.0
    edges = cv2.Canny(roi, CANNY_LOW, CANNY_HIGH)
    return np.sum(edges > 0) / edges.size


def _has_overlap(
    stamp: StampRegion,
    existing: list[StampRegion],
    iou_threshold: float = 0.5,
) -> bool:
    """Check if stamp overlaps significantly with any existing stamp."""
    x1, y1, w1, h1 = stamp.bbox
    area1 = w1 * h1
    if area1 == 0:
        return False

    for other in existing:
        x2, y2, w2, h2 = other.bbox
        ix = max(0, min(x1 + w1, x2 + w2) - max(x1, x2))
        iy = max(0, min(y1 + h1, y2 + h2) - max(y1, y2))
        intersection = ix * iy
        area2 = w2 * h2
        if area2 == 0:
            continue
        iou = intersection / min(area1, area2)
        if iou > iou_threshold:
            return True
    return False
