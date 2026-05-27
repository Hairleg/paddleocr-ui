"""
Author: sizhchan
Org: dgaudit
Version: v0.1
Date: 2026-05-27
"""

"""
Image classifier: distinguish document images from scene/photo images.

Criteria:
  - Face detection (OpenCV Haar Cascade) → scene/photo
  - Text density (PaddleOCR light detection) → document
  - Color complexity (HSV variance) → scene
  - White background dominance → document
"""

import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Thresholds
MIN_TEXT_BOXES = 3       # Minimum OCR text boxes for document classification
MAX_COLOR_VARIANCE = 80  # Maximum HSV channel variance for document
WHITE_BG_THRESHOLD = 0.3  # Minimum ratio of near-white pixels for document


def classify_image(image_path: str) -> dict:
    """
    Classify an image as document or non-document.

    Returns:
        {"status": "ok" | "non_document", "reason": str, "details": dict}
    """
    img = cv2.imread(image_path)
    if img is None:
        return {"status": "non_document", "reason": "Unable to read image",
                "details": {}}

    h, w = img.shape[:2]
    details = {}

    # Check 1: Face detection
    has_face = _detect_face(img)
    details["has_face"] = has_face
    if has_face:
        return {"status": "non_document", "reason": "Person photo detected (face)",
                "details": details}

    # Check 2: White background ratio
    white_ratio = _white_background_ratio(img)
    details["white_ratio"] = round(white_ratio, 3)

    # Check 3: Color complexity
    color_var = _color_variance(img)
    details["color_variance"] = round(color_var, 1)

    # Check 4: Text density via Canny edges on adaptive threshold
    edge_density = _text_edge_density(img)
    details["edge_density"] = round(edge_density, 4)

    # Decision logic
    if white_ratio >= WHITE_BG_THRESHOLD and edge_density >= 0.01:
        return {"status": "ok", "reason": "", "details": details}

    if color_var > MAX_COLOR_VARIANCE and edge_density < 0.02:
        return {"status": "non_document",
                "reason": f"Scene photo (color variance {color_var:.0f}, text density {edge_density:.4f})",
                "details": details}

    if edge_density >= 0.005:
        return {"status": "ok", "reason": "", "details": details}

    return {"status": "non_document",
            "reason": f"Non-document image (text density {edge_density:.4f})",
            "details": details}


def _detect_face(img: np.ndarray) -> bool:
    """Return True if a human face is detected in the image."""
    try:
        # Use OpenCV's built-in Haar cascade for frontal faces
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        face_cascade = cv2.CascadeClassifier(cascade_path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.1, 4, minSize=(30, 30))
        return len(faces) > 0
    except Exception:
        return False


def _white_background_ratio(img: np.ndarray) -> float:
    """Ratio of near-white pixels in the image."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    near_white = np.sum(gray > 230)
    return near_white / gray.size


def _color_variance(img: np.ndarray) -> float:
    """Average variance across HSV channels as a measure of color complexity."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    variances = [np.var(hsv[:, :, c].astype(np.float64)) for c in range(3)]
    return sum(variances) / 3


def _text_edge_density(img: np.ndarray) -> float:
    """Edge density after adaptive thresholding, indicative of text presence."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Adaptive threshold to isolate text strokes
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 11, 2,
    )
    edges = cv2.Canny(binary, 50, 150)
    return np.sum(edges > 0) / edges.size
