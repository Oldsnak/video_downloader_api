# video_downloader_api/api/v1/routes/download_status.py

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from video_downloader_api.core.config import get_settings
from video_downloader_api.db.session import get_db
from video_downloader_api.downloader.ytdlp_downloader import YtDlpDownloader
from video_downloader_api.middleware.auth import verify_api_key
from video_downloader_api.repositories.job_repo import JobRepository
from video_downloader_api.schemas.status import JobStatusOut
from video_downloader_api.services.download_service import DownloadService
from video_downloader_api.services.metadata_service import MetadataService
from video_downloader_api.services.platform_detector import PlatformDetector
from video_downloader_api.services.storage_service import StorageService

router = APIRouter(prefix="/download")


def _download_service(db: Session) -> DownloadService:
    settings = get_settings()
    detector = PlatformDetector()
    downloader = YtDlpDownloader()
    metadata = MetadataService(downloader=downloader, detector=detector)
    storage = StorageService(base_dir=settings.DOWNLOAD_DIR)
    repo_factory = lambda: JobRepository(db)
    return DownloadService(detector=detector, metadata=metadata, storage=storage, repo_factory=repo_factory)


@router.get("/status/{job_id}", response_model=JobStatusOut, dependencies=[Depends(verify_api_key)])
def get_download_status(job_id: str, db: Session = Depends(get_db)) -> JobStatusOut:
    """
    Returns current job status + progress.
    """
    service = _download_service(db)
    try:
        return service.get_status(job_id)
    except ValueError as e:
        # "Job not found."
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
