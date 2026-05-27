"""
Author: sizhchan
Org: dgaudit
Version: v0.1
Date: 2026-05-27
"""

"""
PDF handler: password detection, corruption check, page count.
"""

import logging

logger = logging.getLogger(__name__)


def check_pdf(pdf_path: str) -> dict:
    """
    Check a PDF file for accessibility.

    Returns:
        {
            "status": "ok" | "encrypted" | "corrupt",
            "reason": str (if not ok),
            "page_count": int (if ok),
        }
    """
    try:
        import fitz
        doc = fitz.open(pdf_path)
    except fitz.FileDataError:
        return {"status": "corrupt", "reason": "PDF file is damaged or non-standard"}
    except fitz.FileNotFoundError:
        return {"status": "corrupt", "reason": "PDF file not found"}
    except Exception as e:
        return {"status": "corrupt", "reason": f"Unable to open PDF: {e}"}

    try:
        if doc.needs_pass:
            doc.close()
            return {"status": "encrypted", "reason": "PDF is password-protected"}

        page_count = len(doc)
        doc.close()
        return {"status": "ok", "page_count": page_count}
    except Exception as e:
        try:
            doc.close()
        except Exception:
            pass
        return {"status": "corrupt", "reason": f"PDF read error: {e}"}
