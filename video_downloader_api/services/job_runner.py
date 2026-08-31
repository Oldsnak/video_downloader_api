# video_downloader_api/services/job_runner.py

from __future__ import annotations

import threading

from video_downloader_api.core.config import get_settings
from video_downloader_api.core.logger import get_logger

logger = get_logger("job_runner")


def enqueue_download(job_id: str) -> None:
    """Queue a download without blocking the HTTP request.

    Production: Celery + Redis.
    Codespace / local-without-Redis: a daemon thread in this process, so
    /download/start returns immediately and /status can report live progress.
    """
    settings = get_settings()
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        _run_in_thread(job_id)
        return

    try:
        from video_downloader_api.worker.tasks import run_download

        run_download.delay(job_id)
    except Exception:
        logger.exception(
            "Celery enqueue failed for job_id=%s; running download in-process",
            job_id,
        )
        _run_in_thread(job_id)


def _run_in_thread(job_id: str) -> None:
    thread = threading.Thread(
        target=_run,
        args=(job_id,),
        name=f"download-{job_id[:8]}",
        daemon=True,
    )
    thread.start()


def _run(job_id: str) -> None:
    from video_downloader_api.db.session import SessionLocal
    from video_downloader_api.tasks.download_task import execute_download

    db = SessionLocal()
    try:
        execute_download(job_id=job_id, db=db)
    except Exception:
        logger.exception("In-process download failed for job_id=%s", job_id)
    finally:
        db.close()
