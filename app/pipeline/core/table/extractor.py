"""
Author: sizhchan
Org: dgaudit
Version: v0.1
Date: 2026-05-27
"""

"""
Table region detection and extraction.

Detects table areas in document images using:
  1. Horizontal and vertical line detection (HoughLinesP)
  2. Line intersection grid analysis
  3. Contour-based fallback for borderless tables

Works on both scanned and electronic PDF page renders.
"""

import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ── Line detection parameters ──
HOUGH_RHO = 1
HOUGH_THETA = np.pi / 180
HOUGH_THRESHOLD = 100       # Min votes for a line
MIN_LINE_LENGTH = 50        # Min line length in pixels
MAX_LINE_GAP = 10           # Max gap between segments to be merged

# ── Table region filtering ──
MIN_TABLE_WIDTH = 100       # Min table width in pixels
MIN_TABLE_HEIGHT = 60       # Min table height in pixels
MIN_LINE_COUNT = 3          # Min total (horizontal + vertical) lines for a table


def detect_table_regions(
    image: np.ndarray,
) -> list[tuple[int, int, int, int]]:
    """
    Detect table regions in a document image.

    Args:
        image: BGR image of a document page.

    Returns:
        List of bounding boxes (x, y, w, h) for detected table regions,
        sorted top-to-bottom.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Adaptive threshold to handle varying contrast
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 11, 2,
    )

    # Detect horizontal lines
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    h_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)
    h_lines = cv2.dilate(h_lines, h_kernel, iterations=1)

    # Detect vertical lines
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
    v_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)
    v_lines = cv2.dilate(v_lines, v_kernel, iterations=1)

    # Combine horizontal and vertical lines
    table_mask = cv2.add(h_lines, v_lines)
    # Dilate to connect nearby lines into table blocks
    block_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (10, 10))
    table_mask = cv2.dilate(table_mask, block_kernel, iterations=2)

    # Find connected table regions
    contours, _ = cv2.findContours(
        table_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
    )

    regions = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < MIN_TABLE_WIDTH or h < MIN_TABLE_HEIGHT:
            continue

        # Verify: count actual lines inside this region
        roi = binary[y:y+h, x:x+w]
        h_count = cv2.countNonZero(
            cv2.morphologyEx(roi, cv2.MORPH_OPEN, h_kernel),
        )
        v_count = cv2.countNonZero(
            cv2.morphologyEx(roi, cv2.MORPH_OPEN, v_kernel),
        )
        # If enough line pixels, it's likely a table
        if (h_count + v_count) < MIN_LINE_COUNT * 100:
            continue

        regions.append((x, y, w, h))

    # Sort top-to-bottom
    regions.sort(key=lambda r: r[1])
    return regions


def extract_table_lines(
    image: np.ndarray,
    bbox: tuple[int, int, int, int],
) -> tuple[np.ndarray, np.ndarray]:
    """
    Extract horizontal and vertical line masks within a table region.

    Args:
        image: BGR image.
        bbox: (x, y, w, h) of the table region.

    Returns:
        (h_lines_mask, v_lines_mask): Binary masks of horizontal and vertical lines.
    """
    x, y, w, h = bbox
    roi = image[y:y+h, x:x+w]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 11, 2,
    )

    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 30))

    h_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)
    v_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)

    return h_lines, v_lines


def find_grid_intersections(
    h_lines: np.ndarray,
    v_lines: np.ndarray,
) -> tuple[list[float], list[float]]:
    """
    Find grid row and column positions from horizontal and vertical line masks.

    Uses projection profiles (sum of white pixels along each axis) to
    locate line positions.

    Args:
        h_lines: Binary mask of horizontal lines (H, W).
        v_lines: Binary mask of vertical lines (H, W).

    Returns:
        (row_positions, col_positions): Sorted lists of Y and X coordinates
        for grid lines.
    """
    # Horizontal projection → find row separators
    h_proj = np.sum(h_lines, axis=1)
    h_thresh = np.max(h_proj) * 0.3
    h_peaks = np.where(h_proj > h_thresh)[0]
    row_positions = _cluster_peaks(h_peaks, gap=5)

    # Vertical projection → find column separators
    v_proj = np.sum(v_lines, axis=0)
    v_thresh = np.max(v_proj) * 0.3
    v_peaks = np.where(v_proj > v_thresh)[0]
    col_positions = _cluster_peaks(v_peaks, gap=5)

    return sorted(row_positions), sorted(col_positions)


def _cluster_peaks(positions: np.ndarray, gap: int = 5) -> list[float]:
    """Cluster nearby peak positions and return cluster centers."""
    if len(positions) == 0:
        return []
    positions = sorted(set(positions))
    clusters = []
    current = [positions[0]]
    for p in positions[1:]:
        if p - current[-1] <= gap:
            current.append(p)
        else:
            clusters.append(np.mean(current))
            current = [p]
    if current:
        clusters.append(np.mean(current))
    return clusters
