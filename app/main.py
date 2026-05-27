"""
Author: sizhchan
Org: dgaudit
Version: v0.1
Date: 2026-05-27
"""

"""PaddleOCR UI — FastAPI application entry point."""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api.routes import router
from app.db import init_db
from app.queue import worker, requeue_stale_tasks
from app import __version__

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB, ensure admin, start worker."""
    logger.info("Starting PaddleOCR UI v%s", __version__)

    Path("app/data").mkdir(parents=True, exist_ok=True)
    Path("app/data/outputs").mkdir(parents=True, exist_ok=True)
    await init_db()
    await ensure_admin()
    await requeue_stale_tasks()

    worker_task = asyncio.create_task(worker())
    asyncio.create_task(_warmup_models())

    yield

    worker_task.cancel()
    logger.info("PaddleOCR UI shutting down")


app = FastAPI(
    title="PaddleOCR UI",
    version=__version__,
    description="OCR recognition service with task queue and user accounts.",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": __version__}


async def ensure_admin():
    """Create default admin user from ADMIN_USERNAME/ADMIN_PASSWORD env vars."""
    from app.db import get_db
    from app.auth import hash_password

    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "admin123")

    db = await get_db()
    try:
        row = await db.execute("SELECT id FROM users WHERE username=?", (username,))
        existing = await row.fetchone()
        if not existing:
            pw_hash = hash_password(password)
            await db.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
                (username, pw_hash),
            )
            await db.commit()
            logger.info("Admin user '%s' created", username)
        else:
            logger.info("Admin user '%s' already exists", username)
    finally:
        await db.close()


async def _warmup_models():
    """Background task: pre-load PaddleOCR to trigger ONEDNN compilation."""
    try:
        from app.pipeline.model_cache.preloader import preload_all
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, preload_all)
    except Exception:
        logger.warning("Model pre-warm skipped", exc_info=True)
