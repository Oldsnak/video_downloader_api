# video_downloader_api/tasks/download_task.py

from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

from video_downloader_api.core.config import get_settings
from video_downloader_api.core.logger import get_logger
from video_downloader_api.downloader.ytdlp_downloader import YtDlpDownloader
from video_downloader_api.repositories.job_repo import JobRepository
from video_downloader_api.services.events_service import EventsService
from video_downloader_api.services.file_manager import FileManager
from video_downloader_api.services.progress_service import ProgressService
from video_downloader_api.services.storage_service import StorageService

logger = get_logger("tasks.download_task")


def execute_download(job_id: str, db: Session) -> None:
    """
    Worker-side execution for a download job.

    Steps:
    - set status downloading
    - compute output path
    - call downloader.download(... progress_cb=ProgressService.handle_hook)
    - on success: set status finished + file path/url
    - on error: status failed + error
    """
    settings = get_settings()
    repo = JobRepository(db)

    job = repo.get_job(job_id)
    if not job:
        logger.error("Job not found: %s", job_id)
        return

    storage = StorageService(base_dir=settings.DOWNLOAD_DIR)
    file_manager = FileManager()

    # NOTE: In-memory EventsService will not work across processes in real production.
    # For now, we still publish events (useful when API+worker in same process or for future Redis pubsub).
    events = EventsService()

    # Repo factory that reuses current session/repo
    repo_factory: Callable[[], JobRepository] = lambda: repo
    progress_service = ProgressService(repo_factory=repo_factory, events=events)

    downloader = YtDlpDownloader()

    # Mark job downloading
    repo.update_status(job_id, "downloading", error=None)

    try:
        # Choose extension based on format if you want (default mp4)
        output_path = storage.build_output_path(job_id=job_id, ext="mp4")

        # Cleanup old partials if any
        file_manager.cleanup_job_files(job_id=job_id, base_dir=settings.DOWNLOAD_DIR)

        # Download and stream progress updates through hook
        final_path = downloader.download(
            url=job.source_url,
            format_id=job.format_id or "best",
            output_path=output_path,
            progress_cb=lambda hook: progress_service.handle_hook(job_id, hook),
        )

        # Set finished status + file info
        public_url = storage.public_url_for(job_id)
        repo.set_file(job_id=job_id, file_path=final_path, public_url=public_url)
        repo.update_status(job_id, "finished", error=None)

        # Final event
        events.publish(job_id, {"job_id": job_id, "status": "finished", "public_url": public_url})

    except Exception as e:
        logger.exception("Download failed for job_id=%s", job_id)
        repo.update_status(job_id, "failed", error=str(e))
        events.publish(job_id, {"job_id": job_id, "status": "failed", "error": str(e)})
        # Cleanup partial files on failure
        file_manager.cleanup_job_files(job_id=job_id, base_dir=settings.DOWNLOAD_DIR)
