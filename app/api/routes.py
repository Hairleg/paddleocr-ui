"""
Author: sizhchan
Org: dgaudit
Version: v0.1.2
Date: 2026-06-01
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


# ===== Admin Settings API =====

@router.get("/api/admin/settings")
async def api_admin_get_settings(admin: dict = Depends(admin_required)):
    """Get current runtime settings and resource estimates (admin only)."""
    from app.settings import get, get_int, memory_estimate, get_max_runtime_minutes, DEFAULT_CPU_THREADS, DEFAULT_MAX_CONCURRENT

    threads = get_int("cpu_threads", DEFAULT_CPU_THREADS)
    concurrent = get_int("max_concurrent", DEFAULT_MAX_CONCURRENT)
    runtime = get_max_runtime_minutes()
    mem = memory_estimate(threads)

    return {
        "cpu_threads": threads,
        "max_concurrent": concurrent,
        "max_runtime_minutes": runtime,
        "cpu_cores": os.cpu_count() or 8,
        "memory_mb": mem,
    }


@router.put("/api/admin/settings")
async def api_admin_update_settings(
    data: dict,
    admin: dict = Depends(admin_required),
):
    """Update runtime settings (admin only). Accepted keys: cpu_threads, max_concurrent."""
    from app.settings import set_, save_to_db, get_int, DEFAULT_CPU_THREADS, DEFAULT_MAX_CONCURRENT, DEFAULT_MAX_RUNTIME_MINUTES

    allowed = {"cpu_threads", "max_runtime_minutes"}  # max_concurrent 强制为1
    updated = {}

    for key, val in data.items():
        if key not in allowed:
            continue
        try:
            int_val = int(val)
        except (ValueError, TypeError):
            return JSONResponse(status_code=400, content={"error": f"{key} must be an integer"})
        if key == "cpu_threads":
            int_val = max(1, min(int_val, os.cpu_count() or 8))
        elif key == "max_concurrent":
            int_val = max(1, int_val)
        elif key == "max_runtime_minutes":
            int_val = max(1, int_val)
        set_(key, int_val)
        await save_to_db(key, int_val)
        updated[key] = int_val

    logger.info("Admin settings updated: %s", updated)

    return {
        "status": "ok",
        "updated": updated,
        "note": "Settings applied to new tasks. Active tasks unchanged until next run.",
    }


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

    page_count = precheck.get("total_ok", 0) or sum(f.get("page_count", 0) for f in precheck.get("ok_files", []))
    table_mode = parsed_settings.get("table", False)
    est_min = page_count * 2.0 * (1.5 if table_mode else 1.0)
    est_min = max(5, int(est_min))
    return {"job_id": job_id, "precheck": precheck, "estimated_minutes": est_min}


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
    """List all jobs for current user, with queue position and global stats."""
    db = await get_db()
    try:
        # Global stats
        gc = await db.execute("SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status")
        gr = await gc.fetchall()
        stats = {"total": 0, "queued": 0, "processing": 0, "completed": 0, "failed": 0}
        for r in gr:
            s = r["status"]
            if s in stats: stats[s] = r["cnt"]
            stats["total"] += r["cnt"]
        processed = stats["completed"] + stats["failed"]

        # Queue positions
        qc = await db.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created_at")
        qr = await qc.fetchall()
        queue_map = {r["id"]: i + 1 for i, r in enumerate(qr)}

        cursor = await db.execute(
            """SELECT j.id, j.source_filename, j.status, j.error_message,
                      j.created_at, j.updated_at,
                      (SELECT COUNT(*) FROM job_files WHERE job_id=j.id) as file_count,
                      (SELECT COUNT(*) FROM job_files WHERE job_id=j.id AND status='completed') as completed_files
               FROM jobs j ORDER BY j.created_at DESC LIMIT 50""",
        )
        rows = await cursor.fetchall()
        jobs = []
        for r in rows:
            j = dict(r)
            j["queue_position"] = queue_map.get(j["id"])
            jobs.append(j)

        return {
            "jobs": jobs,
            "stats": {"total": stats["total"], "processed": processed,
                      "queued": stats["queued"], "processing": stats["processing"],
                      "completed": stats["completed"], "failed": stats["failed"]},
        }
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

