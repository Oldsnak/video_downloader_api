# video_downloader_api/repositories/job_repo.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from video_downloader_api.db.models import DownloadJob


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobRepository:
    """
    All database operations related to DownloadJob live here.
    Services/routes should not write SQL directly.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_job(
        self,
        source_url: str,
        platform: str,
        format_id: Optional[str],
        quality: Optional[str],
    ) -> DownloadJob:
        job = DownloadJob(
            source_url=source_url,
            platform=platform,
            status="queued",
            format_id=format_id,
            quality=quality,
            downloaded_bytes=0,
            total_bytes=None,
            speed_bps=None,
            eta_sec=None,
            file_path=None,
            public_url=None,
            error=None,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get_job(self, job_id: str) -> Optional[DownloadJob]:
        stmt = select(DownloadJob).where(DownloadJob.id == job_id)
        return self.db.execute(stmt).scalars().first()

    def update_status(self, job_id: str, status: str, error: Optional[str] = None) -> None:
        job = self.get_job(job_id)
        if not job:
            return
        job.status = status
        job.error = error
        job.updated_at = utc_now()
        self.db.add(job)
        self.db.commit()

    def update_progress(
        self,
        job_id: str,
        downloaded_bytes: int,
        total_bytes: Optional[int],
        speed_bps: Optional[float],
        eta_sec: Optional[int],
    ) -> None:
        job = self.get_job(job_id)
        if not job:
            return

        job.downloaded_bytes = max(0, int(downloaded_bytes))
        job.total_bytes = int(total_bytes) if total_bytes is not None else None
        job.speed_bps = float(speed_bps) if speed_bps is not None else None
        job.eta_sec = int(eta_sec) if eta_sec is not None else None
        job.updated_at = utc_now()

        self.db.add(job)
        self.db.commit()

    def set_file(self, job_id: str, file_path: str, public_url: Optional[str]) -> None:
        job = self.get_job(job_id)
        if not job:
            return

        job.file_path = file_path
        job.public_url = public_url
        job.updated_at = utc_now()

        self.db.add(job)
        self.db.commit()
