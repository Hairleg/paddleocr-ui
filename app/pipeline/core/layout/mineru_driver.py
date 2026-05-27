"""
Author: sizhchan
Org: dgaudit
Version: v0.1
Date: 2026-05-27
"""

"""
MinerU (magic-pdf) driver for electronic PDF structure extraction.

MinerU handles electronic PDF pages that have a text layer:
  - Paragraph structure (blocks, spans, reading order)
  - Table detection and structured JSON extraction
  - Formula (LaTeX) extraction from equation regions
  - Image region detection

For scanned pages (no text layer), MinerU falls back gracefully
and processing is handled by PaddleOCR + opencv instead.
"""

import logging
import json
from typing import Optional

logger = logging.getLogger(__name__)

# MinerU is imported lazily to avoid startup overhead when processing
# only scanned documents.
_mineru_available = False
try:
    import magic_pdf
    _mineru_available = True
except ImportError:
    logger.warning(
        "magic-pdf (MinerU) is not installed. "
        "Electronic PDF structure extraction will be skipped. "
        "Install with: pip install magic-pdf"
    )


def is_available() -> bool:
    """Check if MinerU is installed and ready."""
    return _mineru_available


def extract_structure(
    pdf_path: str,
    output_dir: str,
    page_range: Optional[tuple[int, int]] = None,
) -> dict:
    """
    Extract document structure from an electronic PDF using MinerU.

    Args:
        pdf_path: Path to the PDF file.
        output_dir: Directory for MinerU output files.
        page_range: Optional (start, end) 1-based page range. None = all.

    Returns:
        Dictionary with structure information:
        {
            "pages": [
                {
                    "page_num": 1,
                    "blocks": [...],    # Paragraph blocks with text and positions
                    "tables": [...],    # Table regions with structured data
                    "images": [...],    # Image regions with bounding boxes
                    "formulas": [...],  # Formula regions with LaTeX
                }
            ]
        }
    """
    if not _mineru_available:
        logger.warning("MinerU not available, returning empty structure")
        return {"pages": []}

    try:
        from magic_pdf.pipe.UNIPipe import UNIPipe
        from magic_pdf.rw.DiskReaderWriter import DiskReaderWriter

        # MinerU uses a working directory for intermediate files
        import os
        os.makedirs(output_dir, exist_ok=True)

        # Create reader/writer for disk-based processing
        local_image_dir = os.path.join(output_dir, "images")
        local_md_dir = os.path.join(output_dir, "markdown")
        os.makedirs(local_image_dir, exist_ok=True)
        os.makedirs(local_md_dir, exist_ok=True)

        # Build page range string for MinerU
        if page_range:
            page_str = f"[{page_range[0]},{page_range[1]}]"
        else:
            page_str = None

        # Initialize the MinerU pipeline
        pipe = UNIPipe(
            pdf_bytes=open(pdf_path, "rb").read(),
            jso_useful_key={"_pdf_type": "ocr"},  # Force OCR-aware mode
            image_writer=DiskReaderWriter(local_image_dir),
            is_debug=False,
            start_page_id=page_range[0] - 1 if page_range else 0,
            end_page_id=(page_range[1] - 1) if page_range else None,
        )

        # Run classification and parsing
        pipe.pipe_classify()
        pipe.pipe_parse()

        # Collect content blocks
        content_list = pipe.pipe_mk_uni_format(local_image_dir, drop_mode="none")
        md_content = pipe.pipe_mk_markdown(local_image_dir, drop_mode="none")

        logger.info(
            "MinerU extracted structure: %d content blocks",
            len(content_list),
        )

        return {
            "content_list": content_list,
            "markdown": md_content,
        }

    except Exception as exc:
        logger.error("MinerU extraction failed: %s", exc)
        return {"pages": [], "error": str(exc)}


def extract_page_text(pdf_path: str, page_num: int) -> str:
    """
    Quick text extraction from a single electronic PDF page using PyMuPDF.

    This is a fast alternative for pages confirmed to have a valid text layer.
    """
    import fitz
    doc = fitz.open(pdf_path)
    if page_num < 1 or page_num > len(doc):
        doc.close()
        return ""
    text = doc[page_num - 1].get_text("text")
    doc.close()
    return text


def has_valid_text_layer(pdf_path: str, page_num: int) -> bool:
    """
    Check if a PDF page has a usable text layer.

    Uses the same heuristic as page_router.py but as a standalone check.
    """
    import fitz
    from app.pipeline.core.page_router import classify_page

    doc = fitz.open(pdf_path)
    if page_num < 1 or page_num > len(doc):
        doc.close()
        return False

    page_type = classify_page(doc[page_num - 1])
    doc.close()
    return page_type in ("electronic", "dual_layer")
