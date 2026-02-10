# video_downloader_api/services/download_service.py

from __future__ import annotations

from typing import Callable, Optional

from video_downloader_api.core.config import get_settings
from video_downloader_api.core.logger import get_logger
from video_downloader_api.repositories.job_repo import JobRepository
from video_downloader_api.schemas.download import DownloadStartResponse
from video_downloader_api.schemas.status import JobStatusOut, ProgressOut
from video_downloader_api.services.metadata_service import MetadataService
from video_downloader_api.services.platform_detector import PlatformDetector
from video_downloader_api.services.storage_service import StorageService


class DownloadService:
    """
    High-level orchestration:
    - create download job (DB)
    - enqueue worker task
    - provide status view model
    """

    def __init__(
        self,
        detector: PlatformDetector,
        metadata: MetadataService,
        storage: StorageService,
        repo_factory: Callable[[], JobRepository],
    ) -> None:
        self.detector = detector
        self.metadata = metadata
        self.storage = storage
        self.repo_factory = repo_factory
        self.settings = get_settings()
        self.logger = get_logger(self.__class__.__name__)

    def create_job(self, url: str, format_id: str) -> DownloadStartResponse:
        """
        Creates DB job (queued) and enqueues Celery task.

        Returns:
            DownloadStartResponse containing job_id and helpful URLs for Flutter.
        """
        # Normalize + validate domain + detect platform (and ensure URL is supported)
        normalized = self.detector.normalize_url(url)
        if not self.detector.is_allowed_domain(normalized, self.settings.ALLOWED_DOMAINS):
            raise ValueError("Domain is not allowed.")
        platform = self.detector.detect_platform(normalized)

        # (Optional) You can validate the URL is extractable by calling metadata.validate_and_extract
        # but that can be slow; keeping it light here.
        repo = self.repo_factory()
        job = repo.create_job(
            source_url=normalized,
            platform=platform,
            format_id=format_id,
            quality=None,  # We'll set it later when we match the format during download
        )

        # Enqueue Celery task
        try:
            from video_downloader_api.worker.tasks import run_download  # local import avoids import cycles at startup

            run_download.delay(job.id)
        except Exception:
            self.logger.exception("Failed to enqueue Celery task for job_id=%s", job.id)
            # We still return job_id; status will stay queued and user can retry later.

        status_url = f"{self.settings.API_V1_PREFIX}/download/status/{job.id}"
        stream_url = f"{self.settings.API_V1_PREFIX}/download/stream/{job.id}"

        return DownloadStartResponse(
            job_id=job.id,
            status=job.status,
            status_url=status_url,
            stream_url=stream_url,
            file_url=None,
        )

    def get_status(self, job_id: str) -> JobStatusOut:
        """
        Reads status from DB and returns schema for Flutter.
        """
        repo = self.repo_factory()
        job = repo.get_job(job_id)
        if not job:
            raise ValueError("Job not found.")

        progress: Optional[ProgressOut] = None
        percent: Optional[float] = None
        if job.total_bytes and job.total_bytes > 0:
            percent = round((job.downloaded_bytes / job.total_bytes) * 100.0, 2)

        # Provide progress object if we have any progress numbers
        if job.downloaded_bytes or job.total_bytes or job.speed_bps or job.eta_sec:
            progress = ProgressOut(
                downloaded_bytes=job.downloaded_bytes or 0,
                total_bytes=job.total_bytes,
                speed_bps=job.speed_bps,
                eta_sec=job.eta_sec,
                percent=percent,
            )

        # File URL only if finished and we have it
        public_url = job.public_url
        if not public_url and job.status == "finished":
            public_url = self.storage.public_url_for(job.id)

        return JobStatusOut(
            job_id=job.id,
            status=job.status,
            platform=job.platform,
            source_url=job.source_url,
            format_id=job.format_id,
            quality=job.quality,
            progress=progress,
            file_path=job.file_path,
            public_url=public_url,
            error=job.error,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )
