"""
Author: sizhchan
Org: dgaudit
Version: v0.1.2
Date: 2026-06-01
"""

"""
Model cache preloader: pre-warms PaddleOCR models at application startup.

Without pre-warming, the first OCR request triggers ONEDNN kernel
compilation which can take 5-10 minutes on CPU. This module initializes
PaddleOCR during the FastAPI lifespan startup so the first user request
is fast.

Also handles MinerU model initialization if available.
"""

import logging

logger = logging.getLogger(__name__)

_warmed_up = False


def is_warmed() -> bool:
    """Check if models have been pre-warmed."""
    return _warmed_up


def preload_paddleocr() -> bool:
    """
    Pre-load PaddleOCR singleton to force ONEDNN kernel compilation.

    Returns True if successful, False if import/init failed.
    """
    global _warmed_up

    try:
        logger.info("Pre-warming PaddleOCR models...")
        from app.pipeline.core.ocr.engine import get_ocr

        ocr = get_ocr()
        logger.info("PaddleOCR models pre-warmed successfully")
        _warmed_up = True
        return True

    except ImportError as exc:
        logger.warning(
            "PaddleOCR not available, skipping pre-warm (%s). "
            "OCR will be initialized on first request.",
            exc,
        )
        return False
    except Exception as exc:
        logger.warning("PaddleOCR pre-warm failed: %s", exc)
        return False


def preload_mineru() -> bool:
    """
    Pre-check MinerU availability. Does not load full models
    as MinerU loads models lazily during processing.

    Returns True if the package is importable.
    """
    try:
        import magic_pdf  # noqa: F401
        logger.info("MinerU (magic-pdf) is available")
        return True
    except ImportError:
        logger.info("MinerU (magic-pdf) is not installed")
        return False


def preload_all() -> dict:
    """
    Pre-load all available models during application startup.

    Returns a dict with status for each model.
    """
    status = {
        "paddleocr": preload_paddleocr(),
        "mineru": preload_mineru(),
    }
    logger.info("Model preload complete: %s", status)
    return status
