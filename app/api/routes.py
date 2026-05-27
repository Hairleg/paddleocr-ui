"""
Author: sizhchan
Org: dgaudit
Version: v0.1
Date: 2026-05-27
"""

"""FastAPI routes — auth, jobs, admin, and pages."""

import json
import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

from app.auth import hash_password, verify_password, create_token, current_user, admin_required
from app.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter()

UPLOADS_DIR = Path("app/uploads")
OUTPUT_DIR = Path("app/data/outputs")
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _read_html(filename: str) -> str:
    """Read an HTML template file and return its content."""
    path = TEMPLATES_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "<h1>Page not found</h1>"


# ===== Page routes =====

@router.get("/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse(content=_read_html("login.html"))


@router.get("/register", response_class=HTMLResponse)
async def register_page():
    return HTMLResponse(content=_read_html("register.html"))


@router.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=_read_html("index.html"))


# ===== Auth API =====

@router.post("/api/auth/register")
async def api_register(data: dict):
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "")

    if not username or not password:
        return JSONResponse(status_code=400, content={"error": "Username and password are required."})
    if len(username) < 2 or len(username) > 32:
        return JSONResponse(status_code=400, content={"error": "Username must be 2-32 characters."})
    if len(password) < 4:
        return JSONResponse(status_code=400, content={"error": "Password must be at least 4 characters."})

    db = await get_db()
    try:
        existing = await db.execute("SELECT id FROM users WHERE username=?", (username,))
        if await existing.fetchone():
            return JSONResponse(status_code=409, content={"error": "Username already taken."})

        pw_hash = hash_password(password)
        cursor = await db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, pw_hash),
        )
        await db.commit()
        user_id = cursor.lastrowid
        token = create_token(user_id, username, is_admin=False)
        return {"token": token, "user": {"id": user_id, "username": username, "is_admin": False}}
    finally:
        await db.close()


@router.post("/api/auth/login")
async def api_login(data: dict):
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return JSONResponse(status_code=400, content={"error": "Username and password are required."})

    db = await get_db()
    try:
        row = await db.execute(
            "SELECT id, username, password_hash, is_admin FROM users WHERE username=?",
            (username,),
        )
        user = await row.fetchone()
        if not user or not verify_password(password, user["password_hash"]):
            return JSONResponse(status_code=401, content={"error": "Invalid username or password."})

        token = create_token(user["id"], user["username"], is_admin=bool(user["is_admin"]))
        return {
            "token": token,
            "user": {"id": user["id"], "username": user["username"], "is_admin": bool(user["is_admin"])},
        }
    finally:
        await db.close()


@router.get("/api/auth/me")
async def api_me(user: dict = Depends(current_user)):
    return {"user": user}


@router.post("/api/auth/change-password")
async def api_change_password(data: dict, user: dict = Depends(current_user)):
    old_password = data.get("old_password", "")
    new_password = data.get("new_password", "")

    if not old_password or not new_password:
        return JSONResponse(status_code=400, content={"error": "Both passwords are required."})
    if len(new_password) < 4:
        return JSONResponse(status_code=400, content={"error": "New password must be at least 4 characters."})

    db = await get_db()
    try:
        row = await db.execute(
            "SELECT password_hash FROM users WHERE id=?", (user["id"],)
        )
        u = await row.fetchone()
        if not u or not verify_password(old_password, u["password_hash"]):
            return JSONResponse(status_code=401, content={"error": "Current password is incorrect."})

        new_hash = hash_password(new_password)
        await db.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, user["id"]))
        await db.commit()
        return {"status": "ok"}
    finally:
        await db.close()


# ===== Job API =====

@router.post("/api/jobs/precheck")
async def api_precheck(
    file: UploadFile = File(...),
    settings: str = Form("{}"),
    user: dict = Depends(current_user),
):
    """Upload a file, run precheck, return report. Does NOT enqueue."""
    from app.pipeline.precheck.report import run_precheck

    contents = await file.read()
    filename = file.filename or "unknown"

    # Parse settings (JSON string from multipart form)
    try:
        parsed_settings = json.loads(settings) if settings else {}
    except (json.JSONDecodeError, TypeError):
        parsed_settings = {}

    logger.info("Precheck: user=%s file=%s (%d bytes) settings=%s",
                user["username"], filename, len(contents), parsed_settings)

    # Save uploaded file
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex
    ext = Path(filename).suffix.lower()
    save_path = UPLOADS_DIR / f"{job_id}{ext}"
    save_path.write_bytes(contents)

    # Run real precheck
    precheck = run_precheck(str(save_path), filename)

    # Create job record in precheck status
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO jobs (id, user_id, source_filename, precheck_json, settings) VALUES (?, ?, ?, ?, ?)",
            (job_id, user["id"], filename, json.dumps(precheck, ensure_ascii=False),
             json.dumps(parsed_settings, ensure_ascii=False)),
        )
        await db.commit()
    finally:
        await db.close()

    return {"job_id": job_id, "precheck": precheck}


@router.post("/api/jobs/{job_id}/confirm")
async def api_confirm_job(job_id: str, user: dict = Depends(current_user)):
    """User confirms precheck results → job enters queue."""
    db = await get_db()
    try:
        row = await db.execute(
            "SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, user["id"])
        )
        job = await row.fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        if job["status"] != "precheck":
            return JSONResponse(status_code=400, content={"error": "Job already confirmed."})

        await db.execute(
            "UPDATE jobs SET status='queued', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (job_id,),
        )
        await db.commit()

        # Enqueue for processing
        from app.queue import enqueue_job
        await enqueue_job(job_id)

        return {"job_id": job_id, "status": "queued"}
    finally:
        await db.close()


@router.get("/api/jobs")
async def api_list_jobs(user: dict = Depends(current_user)):
    """List all jobs for current user."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT j.id, j.source_filename, j.status, j.error_message,
                      j.created_at, j.updated_at,
                      (SELECT COUNT(*) FROM job_files WHERE job_id=j.id) as file_count,
                      (SELECT COUNT(*) FROM job_files WHERE job_id=j.id AND status='completed') as completed_files
               FROM jobs j WHERE j.user_id=? ORDER BY j.created_at DESC LIMIT 50""",
            (user["id"],),
        )
        rows = await cursor.fetchall()
        return {"jobs": [dict(r) for r in rows]}
    finally:
        await db.close()


@router.get("/api/jobs/{job_id}")
async def api_get_job(job_id: str, user: dict = Depends(current_user)):
    """Get job details with file statuses."""
    db = await get_db()
    try:
        row = await db.execute(
            "SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, user["id"])
        )
        job = await row.fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")

        files_cursor = await db.execute(
            "SELECT * FROM job_files WHERE job_id=? ORDER BY created_at", (job_id,)
        )
        files = [dict(r) for r in await files_cursor.fetchall()]

        result = dict(job)
        result["files"] = files
        return {"job": result}
    finally:
        await db.close()


@router.get("/api/jobs/{job_id}/download")
async def api_download_job(
    job_id: str,
    user: dict = Depends(current_user),
):
    """Download the ZIP output of a completed job."""
    db = await get_db()
    try:
        row = await db.execute(
            "SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, user["id"])
        )
        job = await row.fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")

        # Find ZIP recursively in output directory
        out_dir = OUTPUT_DIR / job_id
        if out_dir.exists():
            for root, dirs, files in os.walk(str(out_dir)):
                for f in files:
                    if f.endswith(".zip"):
                        full_path = os.path.join(root, f)
                        return FileResponse(full_path, filename=f)

        raise HTTPException(status_code=404, detail="Output not yet available.")
    finally:
        await db.close()


# ===== Job Delete =====

async def _delete_job_disk(job_id: str) -> None:
    """Remove all files associated with a job from disk."""
    import shutil
    import glob as gmod

    # Remove uploaded source files
    for f in gmod.glob(str(UPLOADS_DIR / f"{job_id}.*")):
        try:
            os.remove(f)
        except Exception:
            pass

    # Remove output directory
    out_dir = OUTPUT_DIR / job_id
    if out_dir.exists():
        shutil.rmtree(str(out_dir), ignore_errors=True)


@router.delete("/api/jobs/{job_id}")
async def api_delete_job(job_id: str, user: dict = Depends(current_user)):
    """Delete a single job and all its files."""
    db = await get_db()
    try:
        row = await db.execute(
            "SELECT id FROM jobs WHERE id=? AND user_id=?", (job_id, user["id"])
        )
        if not await row.fetchone():
            raise HTTPException(status_code=404, detail="Job not found.")

        await db.execute("DELETE FROM job_files WHERE job_id=?", (job_id,))
        await db.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        await db.commit()
    finally:
        await db.close()

    await _delete_job_disk(job_id)
    return {"status": "ok"}


@router.delete("/api/jobs")
async def api_delete_all_jobs(user: dict = Depends(current_user)):
    """Delete all jobs for the current user."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM jobs WHERE user_id=?", (user["id"],)
        )
        job_ids = [r["id"] for r in await cursor.fetchall()]

        await db.execute("DELETE FROM job_files WHERE job_id IN (SELECT id FROM jobs WHERE user_id=?)", (user["id"],))
        await db.execute("DELETE FROM jobs WHERE user_id=?", (user["id"],))
        await db.commit()
    finally:
        await db.close()

    for jid in job_ids:
        await _delete_job_disk(jid)

    return {"status": "ok", "deleted": len(job_ids)}


# ===== Admin API =====

@router.get("/api/admin/users")
async def api_admin_list_users(admin: dict = Depends(admin_required)):
    """List all users (admin only)."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, username, is_admin, created_at FROM users ORDER BY created_at"
        )
        rows = await cursor.fetchall()
        return {"users": [dict(r) for r in rows]}
    finally:
        await db.close()


@router.post("/api/admin/users/{user_id}/reset-password")
async def api_admin_reset_password(
    user_id: int,
    data: dict,
    admin: dict = Depends(admin_required),
):
    """Reset a user's password (admin only, no old password needed)."""
    new_password = data.get("new_password", "")
    if len(new_password) < 4:
        return JSONResponse(status_code=400, content={"error": "Password must be at least 4 characters."})

    db = await get_db()
    try:
        pw_hash = hash_password(new_password)
        await db.execute("UPDATE users SET password_hash=? WHERE id=?", (pw_hash, user_id))
        await db.commit()
        return {"status": "ok"}
    finally:
        await db.close()


@router.delete("/api/admin/users/{user_id}")
async def api_admin_delete_user(
    user_id: int,
    admin: dict = Depends(admin_required),
):
    """Delete a user and all their data (admin only)."""
    if user_id == admin["id"]:
        return JSONResponse(status_code=400, content={"error": "Cannot delete yourself."})

    db = await get_db()
    try:
        # Delete job files, jobs, then user
        await db.execute(
            "DELETE FROM job_files WHERE job_id IN (SELECT id FROM jobs WHERE user_id=?)",
            (user_id,),
        )
        await db.execute("DELETE FROM jobs WHERE user_id=?", (user_id,))
        await db.execute("DELETE FROM users WHERE id=?", (user_id,))
        await db.commit()

        # Clean disk
        import shutil
        for d in [UPLOADS_DIR / str(user_id), OUTPUT_DIR / str(user_id)]:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)

        return {"status": "ok"}
    finally:
        await db.close()
