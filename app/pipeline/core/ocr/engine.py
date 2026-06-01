"""
Author: sizhchan
Org: dgaudit
Version: v0.1.2
Date: 2026-06-01
"""

"""
PaddleOCR engine wrapper for version 3.5+.

Uses the new predict() API which takes file paths (not numpy arrays)
and returns OCRResult objects.

Maintains a singleton pattern so the model is loaded once and reused
across all pages in a batch.
"""

import logging
import os
from typing import Optional

# ── Model download source: ModelScope (魔搭) ──
os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "modelscope")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

# ── Multi-core CPU configuration ──
# Reads from app.settings (env PADDLEOCR_CPU_THREADS → admin panel).
# Fallback: PADDLEOCR_NUM_THREADS (legacy env) → auto-detect from memory.
_cpu_count = os.cpu_count() or 4

def _resolve_threads() -> int:
    """Resolve PaddleOCR thread count from settings/env/system."""
    try:
        from app.settings import get_cpu_threads
        return get_cpu_threads()
    except Exception:
        pass
    # Fallback: legacy env → auto-detect
    if "PADDLEOCR_NUM_THREADS" in os.environ:
        return max(1, min(int(os.environ["PADDLEOCR_NUM_THREADS"]), _cpu_count))
    try:
        import psutil
        _avail_gb = psutil.virtual_memory().available / (1024**3)
    except Exception:
        _avail_gb = 16.0
    return max(4, min(_cpu_count, int(_avail_gb / 0.3), 32))

_num_threads = _resolve_threads()

os.environ["OMP_NUM_THREADS"] = str(_num_threads)
os.environ["MKL_NUM_THREADS"] = str(_num_threads)
os.environ.setdefault("PADDLE_PDX_INFER_WORKER_NUM", str(_num_threads))

logger = logging.getLogger(__name__)

logger.info(
    "CPU: %d cores detected, using %d threads for PaddleOCR inference.",
    _cpu_count, _num_threads,
)

from paddleocr import PaddleOCR

# Global OCR instance (lazy-loaded singleton)
_ocr_instance: Optional[PaddleOCR] = None


def get_ocr(lang: str = "ch") -> PaddleOCR:
    """
    Return a cached PaddleOCR instance, creating one if needed.

    PaddleOCR 3.x uses PaddleX under the hood and downloads model
    files to ~/.paddlex/official_models/ on first use.

    On first call, a warmup pass is performed with a tiny dummy image
    to trigger ONEDNN kernel compilation. Without this, the first
    real OCR call would either take 5-10 minutes or return empty results.

    Args:
        lang: Language code, 'ch' for Chinese.

    Returns:
        A ready-to-use PaddleOCR instance.
    """
    global _ocr_instance
    if _ocr_instance is None:
        logger.info(
            "Initializing PaddleOCR 3.x (lang=%s). "
            "ONEDNN kernel compilation may take 5-10 minutes on first run. "
            "Subsequent requests will be fast.",
            lang,
        )
        # Quality parameters disabled for ONNX stability on CPU.
        # Enable for GPU inference or when memory > 32GB:
        #   text_det_limit_side_len=960, text_det_thresh=0.2, text_det_box_thresh=0.4
        _ocr_instance = PaddleOCR(lang=lang)
        logger.info("PaddleOCR initialized, running warmup...")

        # Warmup: trigger ONEDNN compilation with a tiny dummy image
        try:
            import numpy as np, cv2
            dummy = np.ones((100, 100, 3), dtype=np.uint8) * 255
            cv2.imwrite("/tmp/_ocr_warmup.png", dummy)
            _ocr_instance.predict("/tmp/_ocr_warmup.png")
            logger.info("PaddleOCR warmup complete")
        except Exception as exc:
            logger.warning("PaddleOCR warmup had issue (non-fatal): %s", exc)

        logger.info("PaddleOCR engine ready")

    return _ocr_instance


def recognize(image_path: str) -> list[dict]:
    """
    Run OCR on an image file and return structured results.

    Args:
        image_path: Path to a PNG/JPG image file.

    Returns:
        List of dicts with keys: text, confidence, box.
        Example: [{"text": "合同", "confidence": 0.998, "box": [[x1,y1],...]}, ...]
    """
    ocr = get_ocr()
    results = ocr.predict(image_path)

    if not results:
        return []

    # results is a list of OCRResult (one per page/image)
    page_result = results[0]

    rec_texts = page_result.get("rec_texts", []) if hasattr(page_result, 'get') else (getattr(page_result, "rec_texts", []) or [])
    rec_scores = page_result.get("rec_scores", []) if hasattr(page_result, 'get') else (getattr(page_result, "rec_scores", []) or [])
    rec_polys = page_result.get("rec_polys", []) if hasattr(page_result, 'get') else (getattr(page_result, "rec_polys", []) or [])

    output = []
    for i, text in enumerate(rec_texts):
        if not text or not text.strip():
            continue
        confidence = rec_scores[i] if i < len(rec_scores) else 0.0
        poly = rec_polys[i] if i < len(rec_polys) else []
        box = [[int(p[0]), int(p[1])] for p in poly] if len(poly) >= 4 else []

        output.append({
            "text": text.strip(),
            "confidence": round(float(confidence), 4),
            "box": box,
        })

    return output


def predict_ocr(image_path: str, lang: str = "ch"):
    """
    Run OCR and return the raw PaddleOCR 3.5 predict() result.

    This gives access to the full OCRResult object including
    detection polygons, scores, and preprocessor results.

    Args:
        image_path: Path to an image file.
        lang: Language code for OCR model selection.

    Returns:
        List of OCRResult objects.
    """
    ocr = get_ocr(lang)
    return ocr.predict(image_path)
