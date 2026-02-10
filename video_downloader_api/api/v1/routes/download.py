# video_downloader_api/api/v1/routes/download.py

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from video_downloader_api.core.config import get_settings
from video_downloader_api.db.session import get_db
from video_downloader_api.downloader.ytdlp_downloader import YtDlpDownloader
from video_downloader_api.middleware.auth import verify_api_key
from video_downloader_api.middleware.security import validate_url_safe
from video_downloader_api.repositories.job_repo import JobRepository
from video_downloader_api.schemas.download import (
    DownloadStartRequest,
    DownloadStartResponse,
    LinkCheckRequest,
    LinkCheckResponse,
)
from video_downloader_api.schemas.video import VideoInfoOut
from video_downloader_api.services.download_service import DownloadService
from video_downloader_api.services.metadata_service import MetadataService
from video_downloader_api.services.platform_detector import PlatformDetector
from video_downloader_api.services.storage_service import StorageService

router = APIRouter(prefix="/download")


def _build_services(db: Session):
    settings = get_settings()
    detector = PlatformDetector()
    downloader = YtDlpDownloader()
    metadata = MetadataService(downloader=downloader, detector=detector)
    storage = StorageService(base_dir=settings.DOWNLOAD_DIR)
    repo_factory = lambda: JobRepository(db)
    download_service = DownloadService(
        detector=detector,
        metadata=metadata,
        storage=storage,
        repo_factory=repo_factory,
    )
    return settings, detector, metadata, download_service


@router.post("/check", response_model=LinkCheckResponse, dependencies=[Depends(verify_api_key)])
def check_link(payload: LinkCheckRequest, db: Session = Depends(get_db)) -> LinkCheckResponse:
    """
    Validates link, checks allowlisted domain, detects platform.
    """
    settings, detector, _, _ = _build_services(db)

    url_str = str(payload.url)
    validate_url_safe(url_str)

    normalized = detector.normalize_url(url_str)
    if not detector.is_allowed_domain(normalized, settings.ALLOWED_DOMAINS):
        return LinkCheckResponse(
            valid=False,
            platform="unknown",
            normalized_url=None,
            reason="Domain is not allowed.",
        )

    platform = detector.detect_platform(normalized)
    return LinkCheckResponse(
        valid=True,
        platform=platform,
        normalized_url=normalized,
        reason=None,
    )


@router.post("/info", response_model=VideoInfoOut, dependencies=[Depends(verify_api_key)])
def get_info(payload: LinkCheckRequest, db: Session = Depends(get_db)) -> VideoInfoOut:
    """
    Returns video metadata + available formats (quality + size if available).
    """
    settings, _, metadata, _ = _build_services(db)

    url_str = str(payload.url)
    validate_url_safe(url_str)

    try:
        return metadata.get_video_info(url_str, allowed_domains=settings.ALLOWED_DOMAINS)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/start", response_model=DownloadStartResponse, dependencies=[Depends(verify_api_key)])
def start_download(payload: DownloadStartRequest, db: Session = Depends(get_db)) -> DownloadStartResponse:
    """
    Creates a download job and enqueues Celery task.
    """
    _, _, _, download_service = _build_services(db)

    validate_url_safe(payload.url)

    try:
        return download_service.create_job(url=payload.url, format_id=payload.format_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
