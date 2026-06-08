"""
Author: sizhchan
Org: dgaudit
Version: v0.2.0
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
        if not uploads:
            uploads = _gm.glob("app/uploads/{}".format(job_id))
        # 从DB查原始文件名
        from app.db import get_db as _gdb
        _db = await _gdb()
        orig_name = ""
        try:
            row = await _db.execute("SELECT source_filename FROM jobs WHERE id=?", (job_id,))
            jr = await row.fetchone()
            if jr:
                orig_name = jr[0] or ""
        except Exception:
            pass
        finally:
            await _db.close()
        if uploads:
            fpath = uploads[0]
            ext = fpath.rsplit(".", 1)[-1] if "." in fpath else ""
            file_record = {
                "id": job_id,
                "file_path": fpath,
                "file_type": ext,
                "kind": "pdf" if ext.lower() == "pdf" else "image",
                "source_filename": orig_name or fpath
            }
        else:
            file_record = {"id": job_id, "kind": "pdf", "path": "", "source_filename": orig_name or ""}
    await _job_queue.put((job_id, file_record))
    logger.info("Job %s enqueued (queue size ~%d)", job_id, _job_queue.qsize())

async def process_job(job_id: str, file_record: dict):
    logger.info("[JOB] process_job START %s", job_id[:8])
    from app.db import get_db
    db = await get_db()
    logger.info("[JOB] db ok %s", job_id[:8])
    try:
        f = file_record
        file_id = f.get("id") or job_id
        file_path = f.get("path") or f.get("file_path", "")
        if not file_path:
            file_path = job_id
        out_dir = os.path.join("app/data/outputs", job_id)
        os.makedirs(out_dir, exist_ok=True)

        # 更新状态为 processing
        import asyncio
        try:
            await asyncio.wait_for(
                db.execute("UPDATE jobs SET status='processing' WHERE id=?", (job_id,)),
                timeout=5
            )
            await asyncio.wait_for(db.commit(), timeout=5)
        except Exception:
            pass

        if f.get("kind") or f.get("file_type", "") == "pdf":
            import glob as gmod
            pdf_files = gmod.glob("app/uploads/{}.*".format(job_id))
            if not pdf_files:
                pdf_files = gmod.glob("app/uploads/{}".format(job_id))
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
            from functools import partial
            _runner = partial(process_pdf, pdf_path, out_dir, **job_settings)
            try:
                doc_layout = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, _runner),
                    timeout=timeout_sec,
                )
            except asyncio.TimeoutError:
                logger.warning("Job %s: OCR 超时 (limit=%ds)", job_id[:8], timeout_sec)
                try:
                    await _safe_db_op(db, "UPDATE job_files SET status='failed', error_message='timeout' WHERE id=?", (file_id,))
                except Exception:
                    pass
                raise TimeoutError("over time limit")

            # 保存 pkl 用于独立调试
            import pickle as _pk
            with open(os.path.join(out_dir, "doc_layout.pkl"), "wb") as _f:
                _pk.dump(doc_layout, _f)
        else:
            img_path = "app/uploads/{}{}".format(job_id, f.get("type") or f.get("file_type", ".png"))
            if not os.path.exists(img_path):
                raise FileNotFoundError("Image not found")
            from app.pipeline.core.pipeline import process_image
            from functools import partial
            _runner = partial(process_image, img_path, out_dir)
            try:
                doc_layout = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, _runner),
                    timeout=timeout_sec,
                )
            except asyncio.TimeoutError:
                raise TimeoutError("over time limit")

        docx_path = os.path.join(out_dir, "output.docx")
        write_word(doc_layout, docx_path)
        xlsx_path = os.path.join(out_dir, "tables.xlsx")
        write_excel(doc_layout.tables, xlsx_path)

        zip_path = ""
        try:
            from app.pipeline.export.text_writer import write_text
            write_text(doc_layout, os.path.join(out_dir, "output.txt"))
            source_name = f.get("source_filename") or f.get("file_path", "") or f"{job_id[:8]}.pdf"
            zip_path = create_archive(doc_layout, out_dir, job_id[:8], source_name)
        except Exception as exc:
            logger.warning("Archive/text failed: %s", exc)

        await _safe_db_op(db,
            "UPDATE jobs SET status='completed', error_message=NULL WHERE id=?",
            (job_id,))
        await _safe_db_op(db,
            "UPDATE job_files SET status='completed', output_zip=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (zip_path, file_id))
        return True
    except Exception as exc:
        logger.error("Job %s failed", job_id, exc_info=True)
        try:
            await _safe_db_op(db, "UPDATE jobs SET status='failed', error_message='processing error' WHERE id=?", (job_id,))
            await _safe_db_op(db, "UPDATE job_files SET status='failed', updated_at=CURRENT_TIMESTAMP WHERE id=?", (file_id,))
        except:
            pass
        raise
    finally:
        try:
            await asyncio.wait_for(db.close(), timeout=5)
        except Exception:
            pass


async def _safe_db_op(db, sql, params=(), timeout=30):
    """带超时的DB操作，失败不抛异常"""
    try:
        await asyncio.wait_for(db.execute(sql, params), timeout=timeout)
        await asyncio.wait_for(db.commit(), timeout=timeout)
        return True
    except Exception:
        return False

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
        except Exception as _ex:
            logger.error("[W%d] job failed silently: %s", wid, _ex, exc_info=True)
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
        try:
            await asyncio.wait_for(db.close(), timeout=5)
        except Exception:
            pass

async def worker():
    """主 worker 入口，启动 1 个后台 worker"""
    await start_workers(1)
    # 永久等待，worker 在后台运行
    import asyncio
    while True:
        await asyncio.sleep(3600)
