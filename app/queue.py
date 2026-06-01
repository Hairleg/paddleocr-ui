"""
Author: sizhchan
Org: dgaudit
Version: v0.1.2
Date: 2026-06-01
"""

"""Job queue — asyncio.Queue for serial job processing.

One job is processed at a time. Within a job, files are processed sequentially.
Each file goes through: precheck → render → OCR/TextExtract → Word/Excel/ZIP.
"""

import asyncio
import json
import logging
import os
import shutil
import tempfile
import uuid

from app.db import get_db

logger = logging.getLogger(__name__)

# The job queue holds job IDs
job_queue: asyncio.Queue[str] = asyncio.Queue()


async def enqueue_job(job_id: str) -> None:
    """Push a job ID into the processing queue."""
    await job_queue.put(job_id)
    logger.info("Job %s enqueued (queue size ~%d)", job_id, job_queue.qsize())


async def process_job(job_id: str) -> None:
    """
    Process a single job through the full pipeline.

    1. Load precheck data to get file list
    2. For each file: run pipeline → generate Word/Excel → ZIP
    3. Update status in DB
    """
    db = await get_db()
    try:
        # Mark job as processing
        await db.execute(
            "UPDATE jobs SET status='processing', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (job_id,),
        )
        await db.commit()

        # Load job info
        row = await db.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
        job = await row.fetchone()
        if not job:
            return

        precheck = json.loads(job["precheck_json"] or "{}")
        ok_files = precheck.get("ok_files", [])

        if not ok_files:
            await db.execute(
                "UPDATE jobs SET status='failed', error_message='No processable files', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (job_id,),
            )
            await db.commit()
            return

        # Process each file
        from app.pipeline.core.pipeline import process_pdf
        from app.pipeline.export.word_writer import write_word
        from app.pipeline.export.excel_writer import write_excel
        from app.pipeline.export.archiver import create_archive
        from app.pipeline.ir.types import TableData

        completed = 0
        for f in ok_files:
            file_id = f"{uuid.uuid4().hex[:8]}_{f.get('path', 'unknown').replace('/', '_')}"
            await db.execute(
                "INSERT INTO job_files (id, job_id, file_path, file_type, status) VALUES (?, ?, ?, ?, 'processing')",
                (file_id, job_id, f["path"], f.get("type", "")),
            )
            await db.commit()

            try:
                out_dir = f"app/data/outputs/{job_id}/{file_id}"
                os.makedirs(out_dir, exist_ok=True)

                # Run pipeline
                # Read user-configured settings from the job record
                job_settings = {}
                try:
                    raw = job["settings"]
                    if raw:
                        try:
                            job_settings = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            pass
                except (KeyError, IndexError):
                    pass

                if f.get("type") == ".pdf":
                    # Find the physical file
                    import glob as gmod
                    pdf_files = gmod.glob(f"app/uploads/{job_id}.*")
                    pdf_path = pdf_files[0] if pdf_files else None
                    if not pdf_path or not os.path.exists(pdf_path):
                        raise FileNotFoundError("Uploaded file not found")

                    # Run blocking pipeline with configurable timeout
                    from app.settings import get_max_runtime_minutes
                    from functools import partial
                    timeout_sec = get_max_runtime_minutes() * 60
                    _runner = partial(process_pdf, pdf_path, out_dir, **job_settings)
                    try:
                        doc_layout = await asyncio.wait_for(
                            asyncio.get_event_loop().run_in_executor(None, _runner),
                            timeout=timeout_sec,
                        )
                    except asyncio.TimeoutError:
                        raise TimeoutError(
                            f"超过最大运行时间（{get_max_runtime_minutes()}分钟），"
                            f"已停止OCR。若需要更长运行时间，请联系管理员。"
                        )
                else:
                    # Image file
                    img_path = f"app/uploads/{job_id}{f.get('type', '.png')}"
                    if not os.path.exists(img_path):
                        raise FileNotFoundError(f"Image not found: {img_path}")
                    from app.pipeline.core.pipeline import process_image
                    doc_layout = process_image(img_path, out_dir)

                # Write outputs
                docx_path = os.path.join(out_dir, "output.docx")
                write_word(doc_layout, docx_path)
                xlsx_path = os.path.join(out_dir, "tables.xlsx")
                write_excel(doc_layout.tables, xlsx_path)

                # Non-critical: text + archive (failure should not fail the job)
                zip_path = ""
                try:
                    from app.pipeline.export.text_writer import write_text
                    write_text(doc_layout, os.path.join(out_dir, "output.txt"))
                    zip_path = create_archive(doc_layout, out_dir, job_id[:8], f["path"])
                except Exception as exc:
                    logger.warning("Archive/text step failed (non-fatal): %s", exc)

                await db.execute(
                    "UPDATE job_files SET status='completed', output_zip=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (zip_path, file_id),
                )
                await db.commit()
                completed += 1

            except Exception as exc:
                logger.exception("Job %s file %s failed", job_id, f["path"])
                await db.execute(
                    "UPDATE job_files SET status='failed', error_message=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (str(exc), file_id),
                )
                await db.commit()

        # Mark job complete or failed
        if completed == len(ok_files):
            await db.execute(
                "UPDATE jobs SET status='completed', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (job_id,),
            )
        elif completed > 0:
            await db.execute(
                "UPDATE jobs SET status='completed', error_message='Some files failed', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (job_id,),
            )
        else:
            await db.execute(
                "UPDATE jobs SET status='failed', error_message='All files failed', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (job_id,),
            )
        await db.commit()

    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        try:
            await db.execute(
                "UPDATE jobs SET status='failed', error_message=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (str(exc), job_id),
            )
            await db.commit()
        except Exception:
            pass
    finally:
        await db.close()


async def worker() -> None:
    """Background worker: spawn concurrent workers based on settings."""
    from app.settings import get_max_concurrent
    max_workers = get_max_concurrent()
    logger.info("Job worker started (max %d concurrent)", max_workers)

    async def _worker(worker_id: int):
        while True:
            job_id = await job_queue.get()
            try:
                logger.info("[W%d] Processing job %s", worker_id, job_id)
                await process_job(job_id)
            except Exception as exc:
                logger.error("[W%d] Job %s failed: %s", worker_id, job_id, exc)
            finally:
                job_queue.task_done()

    tasks = [asyncio.create_task(_worker(i)) for i in range(max_workers)]
    # Wait forever (workers are infinite loops)
    await asyncio.gather(*tasks)


async def requeue_stale_tasks() -> None:
    """On startup, re-queue any jobs left in 'queued' or 'processing' status."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM jobs WHERE status IN ('queued','processing')"
        )
        rows = await cursor.fetchall()
        for row in rows:
            await enqueue_job(row["id"])
        if rows:
            logger.info("Re-queued %d stale job(s)", len(rows))
    except Exception:
        pass
    finally:
        await db.close()
