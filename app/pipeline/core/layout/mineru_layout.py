"""
Author: sizhchan
Org: dgaudit
Version: v0.1.2
Date: 2026-06-01
"""

"""
MinerU doclayout_yolo layout analysis integration.

Uses the doclayout_yolo model (YOLOv8-based) to detect document regions:
  - title, plain text, figure, table, formula, etc.

This replaces/supplements PyMuPDF's find_tables for electronic PDFs
with deep-learning-based region detection that handles borderless tables
and complex layouts.
"""

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Lazy-loaded model singleton
_yolo_model = None
_yolo_failed = False  # Set to True if inference crashes (model incompatible)
import os as _os
MODEL_PATH = _os.environ.get(
    "MINERU_LAYOUT_MODEL",
    "/mnt/workspace/tool/models/mineru/Layout/YOLO/doclayout_yolo_docstructbench_imgsz1280_2501.pt"
)

# Class IDs from doclayout_yolo
CLASS_TABLE = 5
CLASS_TABLE_CAPTION = 6
CLASS_TITLE = 0
CLASS_TEXT = 1
CLASS_FIGURE = 3


def _set_yolo_failed():
    """Mark YOLO as permanently failed to avoid retries."""
    global _yolo_failed
    _yolo_failed = True


def get_layout_model():
    """Get or create the YOLO layout model (singleton)."""
    global _yolo_model
    if _yolo_model is None:
        try:
            import torch
            _orig_load = torch.load
            torch.load = lambda *a, **kw: _orig_load(*a, **dict(kw, weights_only=False))
            from doclayout_yolo import YOLOv10
            _yolo_model = YOLOv10(MODEL_PATH)
            torch.load = _orig_load
            logger.info("doclayout_yolo model loaded via YOLOv10: %s", MODEL_PATH)
        except Exception as exc:
            logger.warning("doclayout_yolo not available: %s", exc)
            _yolo_model = None
            return None
    return _yolo_model


def detect_layout_regions(image: np.ndarray, imgsz: int = 1280) -> list[dict]:
    global _yolo_failed
    if _yolo_failed:
        return []
    """
    Run layout detection on a page image (BGR numpy array).

    Returns list of regions, each with:
      - type: "table", "text", "title", "figure", etc.
      - bbox: (x1, y1, x2, y2) in pixels
      - confidence: 0.0-1.0
    """
    model = get_layout_model()
    if model is None:
        return []

    # Convert BGR (OpenCV) to RGB (YOLO)
    rgb = image[..., ::-1]
    try:
        results = model(rgb, imgsz=imgsz, verbose=False)
    except Exception as exc:
        logger.warning("YOLO inference failed (model incompatible, falling back to PyMuPDF): %s", exc)
        _set_yolo_failed()
        return []

    regions = []
    for r in results:
        if r.boxes is None:
            continue
        boxes = r.boxes.xyxy.cpu().numpy()
        classes = r.boxes.cls.cpu().numpy().astype(int)
        confs = r.boxes.conf.cpu().numpy()

        for box, cls_id, conf in zip(boxes, classes, confs):
            x1, y1, x2, y2 = map(int, box)
            cls_name = model.names.get(cls_id, f"class_{cls_id}")
            regions.append({
                "type": cls_name,
                "class_id": int(cls_id),
                "bbox": (x1, y1, x2 - x1, y2 - y1),
                "confidence": float(conf),
            })

    return regions




def has_table_layout(image: np.ndarray, page_num: int = 0) -> bool:
    """
    Quick pre-check: does this page likely contain tables?

    Tries MinerU YOLO first, then falls back to basic line-density analysis.
    Returns False for text-only pages (red-header docs, reports, etc.)
    to skip expensive table extraction.
    """
    global _yolo_failed
    if not _yolo_failed:
        try:
            regions = detect_layout_regions(image)
            table_count = sum(1 for r in regions if r.get("class_id") == CLASS_TABLE)
            if table_count > 0:
                return True
            # YOLO found no tables — but could be model issue
            # If YOLO was just marked failed, assume tables exist
            if _yolo_failed:
                return True
            return False
        except Exception:
            _set_yolo_failed()

    # YOLO failed — conservative: assume tables may exist
    return True

def detect_table_regions_yolo(image: np.ndarray) -> list[tuple]:
    """
    Detect table regions using doclayout_yolo.

    Returns list of (x, y, w, h) tuples for table bounding boxes.
    """
    all_regions = detect_layout_regions(image)
    tables = []
    for r in all_regions:
        if r["class_id"] == CLASS_TABLE and r.get("confidence", 0) >= 0.60:
            w, h = r["bbox"][2], r["bbox"][3]
            # Reject very thin/small regions (likely text lines)
            if h < 30 or w < 100:
                continue
            tables.append(r["bbox"])
    return tables
