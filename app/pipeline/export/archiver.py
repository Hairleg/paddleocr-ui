"""
Author: sizhchan
Org: dgaudit
Version: v0.2.0
Date: 2026-06-01
"""

"""
ZIP archiver for OCR output products.

Packages all output files (Word, Excel, images, reports)
into a single ZIP archive for user download.
"""

import logging
import os
import zipfile
from pathlib import Path
from datetime import datetime

from app.pipeline.ir.types import DocumentLayout

logger = logging.getLogger(__name__)


def create_archive(
    doc_layout: DocumentLayout,
    output_dir: str,
    task_id: str,
    source_filename: str,
    error_report: str | None = None,
) -> str:
    """
    Create the final output ZIP archive.

    Archive name: {原始文件名}_{时间戳}.zip
    Contents:
        ├── output.docx
        ├── tables.xlsx
        ├── images/
        │   ├── stamps/
        │   └── photos/
        ├── precheck_report.txt
        └── error_report.txt
    """
    stem = Path(source_filename).stem
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"{stem}_ocr_{ts}.zip"
    docx_arc = f"{stem}_ocr_{ts}.docx"
    xlsx_arc = f"{stem}_ocr_{ts}.xlsx"
    zip_path = os.path.join(output_dir, zip_name)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:

        # Add Word document
        docx_path = os.path.join(output_dir, "output.docx")
        if os.path.exists(docx_path):
            zf.write(docx_path, docx_arc)

        # Add Excel file
        xlsx_path = os.path.join(output_dir, "tables.xlsx")
        if os.path.exists(xlsx_path):
            zf.write(xlsx_path, xlsx_arc)

        # Add plain text file
        txt_path = os.path.join(output_dir, "output.txt")
        txt_arc = f"{stem}_ocr_{ts}.txt"
        if os.path.exists(txt_path):
            zf.write(txt_path, txt_arc)

        # Add image directories
        _add_directory_to_zip(zf, output_dir, "images/stamps", "images/stamps")
        _add_directory_to_zip(zf, output_dir, "images/photos", "images/photos")

        # Add error report if present
        if error_report:
            report_path = _write_temp_report(output_dir, "error_report.txt", error_report)
            zf.write(report_path, "error_report.txt")

    logger.info("Archive created: %s (%d bytes)", zip_path, os.path.getsize(zip_path))
    return zip_path


def create_precheck_archive(
    output_dir: str,
    task_id: str,
    precheck_report: str,
) -> str:
    """Create a ZIP containing only the precheck report."""
    zip_name = f"precheck_{task_id}.zip"
    zip_path = os.path.join(output_dir, zip_name)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        report_path = _write_temp_report(output_dir, "precheck_report.txt", precheck_report)
        zf.write(report_path, "precheck_report.txt")

    return zip_path


def _add_directory_to_zip(
    zf: zipfile.ZipFile,
    base_dir: str,
    dir_name: str,
    arc_prefix: str,
) -> None:
    """Add all files from a directory to the ZIP archive."""
    dir_path = os.path.join(base_dir, dir_name)
    if not os.path.isdir(dir_path):
        return

    for root, dirs, files in os.walk(dir_path):
        for filename in files:
            file_path = os.path.join(root, filename)
            arc_name = os.path.join(arc_prefix, filename)
            zf.write(file_path, arc_name)


def _write_temp_report(output_dir: str, filename: str, content: str) -> str:
    """Write a text report to a temp file and return its path."""
    path = os.path.join(output_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path
