"""
Author: sizhchan
Org: dgaudit
Version: v0.1
Date: 2026-05-27
"""

"""
ZIP handler: recursive extraction, password detection, file enumeration.

Supports ZIP_STORED, ZIP_DEFLATED, ZIP_BZIP2, ZIP_LZMA algorithms.
Nested ZIPs are extracted up to max_depth=3.
Password-protected entries are detected and reported as errors.
"""

import logging
import zipfile
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_DEPTH = 3  # Maximum nested ZIP extraction depth
SUPPORTED_EXTS = {".pdf", ".jpg", ".jpeg", ".png"}


def enumerate_zip(
    zip_path: str,
    extract_dir: str,
    depth: int = 0,
) -> dict:
    """
    Recursively enumerate and extract files from a ZIP archive.

    Args:
        zip_path: Path to the ZIP file.
        extract_dir: Directory for extracted files.
        depth: Current recursion depth (starts at 0).

    Returns:
        {
            "ok_files": [{"path": "archive/a.pdf", "type": ".pdf"}],
            "bad_files": [{"path": "archive/secret.pdf", "reason": "encrypted"}],
        }
    """
    result = {"ok_files": [], "bad_files": []}

    if depth > MAX_DEPTH:
        result["bad_files"].append({
            "path": zip_path,
            "reason": f"ZIP nested beyond max depth ({MAX_DEPTH})",
        })
        return result

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            infolist = zf.infolist()

            for info in infolist:
                # Skip directories
                if info.is_dir():
                    continue

                internal_path = info.filename
                ext = Path(internal_path).suffix.lower()

                # Check if encrypted
                if info.flag_bits & 0x1:
                    result["bad_files"].append({
                        "path": f"{zip_path}/{internal_path}",
                        "reason": "encrypted",
                    })
                    continue

                # Extract to temp location
                try:
                    extracted = zf.extract(info, extract_dir)
                except RuntimeError as e:
                    if "password" in str(e).lower():
                        result["bad_files"].append({
                            "path": f"{zip_path}/{internal_path}",
                            "reason": "encrypted",
                        })
                    else:
                        result["bad_files"].append({
                            "path": f"{zip_path}/{internal_path}",
                            "reason": f"extraction error: {e}",
                        })
                    continue

                # Handle nested ZIPs
                if ext == ".zip":
                    sub = enumerate_zip(extracted, extract_dir, depth + 1)
                    # Prefix paths with ZIP internal path
                    for f in sub["ok_files"]:
                        f["path"] = f"{internal_path}/{f['path']}"
                    for f in sub["bad_files"]:
                        f["path"] = f"{internal_path}/{f['path']}"
                    result["ok_files"].extend(sub["ok_files"])
                    result["bad_files"].extend(sub["bad_files"])
                    continue

                # Supported file types
                if ext in SUPPORTED_EXTS:
                    result["ok_files"].append({
                        "path": internal_path,
                        "type": ext,
                        "extracted_path": extracted,
                    })
                else:
                    result["bad_files"].append({
                        "path": f"{zip_path}/{internal_path}",
                        "reason": f"unsupported format ({ext})",
                    })

    except zipfile.BadZipFile:
        result["bad_files"].append({
            "path": zip_path,
            "reason": "corrupt or invalid ZIP",
        })
    except Exception as e:
        result["bad_files"].append({
            "path": zip_path,
            "reason": str(e),
        })

    return result


def check_zip_password(zip_path: str) -> bool:
    """Return True if ZIP is password-protected."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            info = zf.infolist()[0]
            zf.read(info)
            return False
    except RuntimeError as e:
        return "password" in str(e).lower() or "encrypted" in str(e).lower()
    except Exception:
        return False
