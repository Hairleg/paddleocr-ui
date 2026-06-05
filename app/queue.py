"""
Author: sizhchan
Org: dgaudit
Version: v0.1.2
Date: 2026-06-01
"""

"""Job queue — asyncio.Queue for serial job processing."""

import asyncio
import json
import logging
import os
import shutil
import tempfile
import uuid
from functools import partial

from app.db import get_db
from app.pipeline.core.pipeline import process_pdf, process_image
from app.pipeline.export.word_writer import write_word
from app.pipeline.export.excel_writer import write_excel
from app.pipeline.export.archiver import create_archive

logger = logging.getLogger(__name__)

_job_queue = asyncio.Queue(maxsize=50)
_worker_count = 0

async def enqueue_job(job_id: str, file_record: dict = None):
    if file_record is None:
        import glob as _gm
        # 从上传目录找到文件
        uploads = _gm.glob("app/uploads/{}.*".format(job_id))
        if uploads:
            fpath = uploads[0]
            ext = fpath.rsplit(".", 1)[-1] if "." in fpath else ""
            file_record = {
                "id": job_id,
                "file_path": fpath,
                "file_type": ext,
                "kind": "pdf" if ext.lower() == "pdf" else "image"
            }
        else:
            file_record = {"id": job_id, "kind": "pdf", "path": ""}
    await _job_queue.put((job_id, file_record))
    logger.info("Job %s enqueued (queue size ~%d)", job_id, _job_queue.qsize())

async def process_job(job_id: str, file_record: dict):
    from app.db import get_db
    db = await get_db()
    try:
        f = file_record
        file_id = f.get("id") or job_id
        file_path = f.get("path") or f.get("file_path", "")
        if not file_path:
            file_path = job_id
        out_dir = os.path.join("app/data/outputs", job_id)
        os.makedirs(out_dir, exist_ok=True)

        if f.get("kind") or f.get("file_type", "") == "pdf":
            import glob as gmod
            pdf_files = gmod.glob("app/uploads/{}.*".format(job_id))
            pdf_path = pdf_files[0] if pdf_files else None
            if not pdf_path or not os.path.exists(pdf_path):
                raise FileNotFoundError("Uploaded file not found")

            job_settings = {
                "lang": f.get("lang", "ch"),
                "dpi": f.get("dpi", 200),
                "enable_table": f.get("table", False),
                "enable_table_merge": f.get("table_merge", False),
            }
            from app.settings import get_max_runtime_minutes
            timeout_sec = get_max_runtime_minutes() * 60
            # 子进程隔离：避免 ONEDNN SIGSEGV 杀死 uvicorn
            import sys as _sys
            import json as _json
            worker_script = f'''
import sys, os, pickle, json
sys.path.insert(0, "/mnt/workspace/project/paddleocr-ui")
os.environ["PADDLE_PDX_MODEL_SOURCE"] = "modelscope"
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["FLAGS_enable_pir_api"] = "False"
from app.pipeline.core.pipeline import process_pdf
doc = process_pdf({pdf_path!r}, {out_dir!r}, **{repr(job_settings)})
# 结果已在 process_pdf 内部写入磁盘
print("OK", flush=True)
'''
            proc = await asyncio.create_subprocess_exec(
                _sys.executable, "-c", worker_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                close_fds=True,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_sec
            )
            if proc.returncode != 0:
                err = stderr.decode()[-500:] if stderr else "unknown"
                raise RuntimeError(f"OCR subprocess failed (exit={proc.returncode}): {err}")
        else:
            img_path = "app/uploads/{}{}".format(job_id, f.get("type") or f.get("file_type", ".png"))
            if not os.path.exists(img_path):
                raise FileNotFoundError("Image not found")
            doc_layout = process_image(img_path, out_dir)

        docx_path = os.path.join(out_dir, "output.docx")
        xlsx_path = os.path.join(out_dir, "tables.xlsx")

        zip_path = ""
        try:
            from app.pipeline.export.text_writer import write_text
            write_text(doc_layout, os.path.join(out_dir, "output.txt"))
            zip_path = create_archive(doc_layout, out_dir, job_id[:8], f["path"])
        except Exception as exc:
            logger.warning("Archive/text failed: %s", exc)

        await db.execute(
            "UPDATE job_files SET status='completed', output_zip=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (zip_path, file_id),
        )
        await db.commit()
        return True
    except Exception as exc:
        logger.error("Job %s failed", job_id, exc_info=True)
        try:
            await db.execute("UPDATE job_files SET status='failed', updated_at=CURRENT_TIMESTAMP WHERE id=?", (file_id,))
            await db.commit()
        except:
            pass
        raise
    finally:
        await db.close()

async def start_workers(n: int = 1):
    global _worker_count
    for i in range(n):
        _worker_count += 1
        asyncio.create_task(_worker(_worker_count))

async def _worker(wid: int):
    while True:
        job_id, file_record = await _job_queue.get()
        try:
            logger.info("[W%d] Processing job %s", wid, job_id)
            await process_job(job_id, file_record)
        except Exception:
            pass
        finally:
            _job_queue.task_done()

# ── 兼容 main.py 入口 ──
async def requeue_stale_tasks():
    """重启时把 processing 状态的任务重置为 pending"""
    from app.db import get_db
    db = await get_db()
    try:
        await db.execute("UPDATE job_files SET status='pending' WHERE status='processing'")
        await db.commit()
    except Exception:
        pass
    finally:
        await db.close()

async def worker():
    """主 worker 入口，启动 1 个后台 worker"""
    await start_workers(1)
    # 永久等待，worker 在后台运行
    import asyncio
    while True:
        await asyncio.sleep(3600)
