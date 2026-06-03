"""
Author: sizhchan
Org: dgaudit
Version: v0.1.2
Date: 2026-06-01
"""

"""Runtime admin settings — CPU threads, concurrency, resource estimates.
Values are loaded from DB on startup, overridable via env PADDLEOCR_CPU_THREADS / PADDLEOCR_MAX_CONCURRENT.
"""

import os
import logging

logger = logging.getLogger(__name__)

# ── Defaults (tuned by admin, production: 8c16GB) ──
DEFAULT_CPU_THREADS = 8      # PaddleOCR OpenMP/MKL threads per task
DEFAULT_MAX_CONCURRENT = 0   # 0 = auto-detect (cores * 0.75 / 8)
DEFAULT_MAX_RUNTIME_MINUTES = 15  # Per-task timeout before auto-cancellation

# ── Memory model (PaddleOCR ONNX, PP-OCRv5) ──
MEMORY_BASE_MB = 600         # det + rec model weights (~300 MB each)
MEMORY_PER_THREAD_MB = 300   # workspace buffers per thread

# ── In-memory cache ──
_settings: dict[str, str] = {}


def get(key: str, default: str = "") -> str:
    val = _settings.get(key)
    if val is None or val == "":
        val = os.environ.get(f"PADDLEOCR_{key.upper()}", "")
    if val == "":
        val = str(default)
    return val


def set_(key: str, value) -> None:
    _settings[key] = str(value)


def get_int(key: str, default: int) -> int:
    try:
        return int(get(key, str(default)))
    except (ValueError, TypeError):
        return default


def get_cpu_threads() -> int:
    val = get_int("cpu_threads", DEFAULT_CPU_THREADS)
    cpu_count = os.cpu_count() or 8
    return max(1, min(val, cpu_count))


def get_max_concurrent() -> int:
    val = get_int("max_concurrent", DEFAULT_MAX_CONCURRENT)
    if val <= 0:
        # Auto: ~75% CPU across ONEDNN-effective threads (~8/task)
        cores = os.cpu_count() or 4
        val = max(1, (cores + 3) // 8)  # ceil(cores/8) ≈ 80% CPU
        # Cap at 8 concurrent tasks (stability)
        val = min(val, 8)
    return max(1, val)


def get_max_runtime_minutes() -> int:
    return max(1, get_int("max_runtime_minutes", DEFAULT_MAX_RUNTIME_MINUTES))


def memory_estimate(threads: int | None = None) -> dict:
    t = threads or get_cpu_threads()
    per_task = MEMORY_BASE_MB + MEMORY_PER_THREAD_MB * t
    concurrent = get_max_concurrent()
    return {
        "base_model_mb": MEMORY_BASE_MB,
        "per_thread_mb": MEMORY_PER_THREAD_MB,
        "threads": t,
        "per_task_mb": per_task,
        "max_concurrent": concurrent,
        "peak_total_mb": per_task * concurrent,
        "recommendation": (
            f"{concurrent} 并发 × {t} 线程/任务 ≈ {per_task * concurrent} MB 峰值。"
            f"单任务 {per_task} MB，建议预留 {(per_task * concurrent * 1.5):.0f} MB 系统内存。"
        ),
    }


async def load_from_db() -> None:
    from app.db import get_db
    db = await get_db()
    try:
        cursor = await db.execute("SELECT key, value FROM app_settings")
        rows = await cursor.fetchall()
        for row in rows:
            _settings[row["key"]] = row["value"]
        logger.info("Loaded %d settings from DB", len(rows))
    except Exception:
        logger.info("app_settings table not ready, using defaults")
    finally:
        await db.close()


async def save_to_db(key: str, value: str) -> None:
    from app.db import get_db
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            (key, str(value)),
        )
        await db.commit()
    finally:
        await db.close()
