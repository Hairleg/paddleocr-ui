"""
Author: sizhchan
Org: dgaudit
Version: v0.1
Date: 2026-05-27
"""

"""SQLite database module — async connection, init, and query helpers."""

import os
import logging

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("PADDLEOCR_DB_PATH", "app/data/paddleocr.db")
ADMIN_DEFAULT_PASSWORD = os.environ.get("PADDLEOCR_ADMIN_PASSWORD", "admin123")


async def get_db() -> aiosqlite.Connection:
    """Create a new async SQLite connection with WAL + foreign keys enabled."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db() -> None:
    """Create tables and seed admin user if needed."""
    db = await get_db()
    try:
        # ── Schema ──
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                username        TEXT UNIQUE NOT NULL,
                password_hash   TEXT NOT NULL,
                is_admin        INTEGER DEFAULT 0,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id              TEXT PRIMARY KEY,
                user_id         INTEGER NOT NULL,
                source_filename TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'precheck',
                precheck_json   TEXT,
                error_message   TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS job_files (
                id              TEXT PRIMARY KEY,
                job_id          TEXT NOT NULL,
                file_path       TEXT NOT NULL,
                file_type       TEXT NOT NULL,
                page_count      INTEGER,
                status          TEXT NOT NULL DEFAULT 'pending',
                output_zip      TEXT,
                error_message   TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs(id)
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id);
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_job_files_job_id ON job_files(job_id);
        """)
        await db.commit()

        # ── Migrate: add is_admin column if missing (upgrade from old schema) ──
        try:
            await db.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
            await db.commit()
        except Exception:
            pass  # column already exists

        # ── Migrate: add settings column to jobs ──
        try:
            await db.execute("ALTER TABLE jobs ADD COLUMN settings TEXT DEFAULT '{}'")
            await db.commit()
        except Exception:
            pass  # column already exists

        # ── Seed admin user ──
        cursor = await db.execute("SELECT COUNT(*) FROM users WHERE is_admin=1")
        row = await cursor.fetchone()
        if row and row[0] == 0:
            from app.auth import hash_password
            pw_hash = hash_password(ADMIN_DEFAULT_PASSWORD)
            await db.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
                ("admin", pw_hash),
            )
            await db.commit()
            logger.info("Admin user 'admin' created (default password: admin123)")

        logger.info("Database initialized at %s", DB_PATH)
    finally:
        await db.close()
