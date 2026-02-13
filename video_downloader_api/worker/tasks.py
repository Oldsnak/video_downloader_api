from __future__ import annotations

from sqlalchemy.orm import Session

from video_downloader_api.core.logger import get_logger
from video_downloader_api.db.session import SessionLocal
from video_downloader_api.worker.celery_app import celery_app

logger = get_logger("worker.tasks")


@celery_app.task(name="worker.tasks.run_download")
def run_download(job_id: str) -> None:
    db: Session = SessionLocal()
    try:
        from video_downloader_api.tasks.download_task import execute_download
        execute_download(job_id=job_id, db=db)
    except Exception:
        logger.exception("run_download failed for job_id=%s", job_id)
        raise
    finally:
        db.close()
