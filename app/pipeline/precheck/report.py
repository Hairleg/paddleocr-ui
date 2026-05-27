"""
Author: sizhchan
Org: dgaudit
Version: v0.1
Date: 2026-05-27
"""

"""
Precheck report generator.

Coordinates ZIP extraction, PDF checks, and image classification
to produce a unified precheck report for a user upload.
"""

import json
import logging
import os
import tempfile
from pathlib import Path

from app.pipeline.precheck.zip_handler import enumerate_zip
from app.pipeline.precheck.pdf_handler import check_pdf
from app.pipeline.precheck.image_classifier import classify_image

logger = logging.getLogger(__name__)

SUPPORTED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".zip"}


def run_precheck(file_path: str, original_filename: str) -> dict:
    """
    Run precheck on an uploaded file.

    Returns a precheck report dict:
    {
        "ok_files": [{"path": "a.pdf", "type": ".pdf", "page_count": 16}],
        "bad_files": [{"path": "x.doc", "reason": "unsupported format"}],
        "total_ok": int,
        "total_bad": int,
        "can_proceed": bool,
    }
    """
    ok_files = []
    bad_files = []
    tmpdir = tempfile.mkdtemp(prefix="precheck_")

    try:
        ext = Path(original_filename).suffix.lower()

        # ── ZIP ──
        if ext == ".zip":
            result = enumerate_zip(file_path, tmpdir)
            for f in result["ok_files"]:
                _classify_extracted(f, ok_files, bad_files)
            for f in result["bad_files"]:
                bad_files.append(f)

        # ── PDF ──
        elif ext == ".pdf":
            pdf_result = check_pdf(file_path)
            if pdf_result["status"] == "ok":
                ok_files.append({
                    "path": original_filename,
                    "type": ".pdf",
                    "page_count": pdf_result.get("page_count"),
                })
            else:
                bad_files.append({
                    "path": original_filename,
                    "reason": pdf_result["reason"],
                })

        # ── Image ──
        elif ext in (".jpg", ".jpeg", ".png"):
            img_result = classify_image(file_path)
            if img_result["status"] == "ok":
                ok_files.append({
                    "path": original_filename,
                    "type": ext,
                })
            else:
                bad_files.append({
                    "path": original_filename,
                    "reason": img_result["reason"],
                })

        # ── Unsupported ──
        else:
            bad_files.append({
                "path": original_filename,
                "reason": f"Unsupported format ({ext})",
            })

    except Exception as exc:
        logger.exception("Precheck error")
        bad_files.append({
            "path": original_filename,
            "reason": f"Precheck error: {exc}",
        })
    finally:
        # Clean temp dir
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    return {
        "ok_files": ok_files,
        "bad_files": bad_files,
        "total_ok": len(ok_files),
        "total_bad": len(bad_files),
        "can_proceed": len(ok_files) > 0,
    }


def _classify_extracted(file_entry: dict, ok_files: list, bad_files: list) -> None:
    """Check and classify a file extracted from ZIP."""
    path = file_entry.get("path", "")
    ext = file_entry.get("type", "").lower()
    extracted = file_entry.get("extracted_path", "")

    if ext == ".pdf":
        pdf_result = check_pdf(extracted) if extracted else {"status": "corrupt"}
        if pdf_result["status"] == "ok":
            ok_files.append({
                "path": path,
                "type": ".pdf",
                "page_count": pdf_result.get("page_count"),
            })
        else:
            bad_files.append({"path": path, "reason": pdf_result["reason"]})

    elif ext in (".jpg", ".jpeg", ".png"):
        img_result = classify_image(extracted) if extracted else {"status": "non_document"}
        if img_result["status"] == "ok":
            ok_files.append({"path": path, "type": ext})
        else:
            bad_files.append({"path": path, "reason": img_result["reason"]})

    else:
        bad_files.append({"path": path, "reason": f"Unsupported format ({ext})"})


def generate_report_text(precheck: dict) -> str:
    """Generate a human-readable TXT report from precheck data."""
    lines = []
    lines.append("PaddleOCR UI - Precheck Report")
    lines.append("=" * 40)
    lines.append("")

    if precheck["ok_files"]:
        lines.append(f"--- OK: {len(precheck['ok_files'])} file(s) ---")
        for f in precheck["ok_files"]:
            extra = f" ({f.get('page_count', '?')} pages)" if f.get("page_count") else ""
            lines.append(f"  {f['path']}{extra}")
        lines.append("")

    if precheck["bad_files"]:
        lines.append(f"--- SKIPPED: {len(precheck['bad_files'])} file(s) ---")
        for f in precheck["bad_files"]:
            lines.append(f"  {f['path']} - {f.get('reason', 'unknown')}")
        lines.append("")

    lines.append(f"Total: {precheck['total_ok']} OK, {precheck['total_bad']} skipped")
    if precheck["can_proceed"]:
        lines.append("Status: CAN PROCEED")
    else:
        lines.append("Status: NO PROCESSABLE FILES")

    return "\n".join(lines)
