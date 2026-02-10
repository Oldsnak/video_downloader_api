# video_downloader_api/api/v1/routes/files.py

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from video_downloader_api.core.config import get_settings
from video_downloader_api.db.session import get_db
from video_downloader_api.middleware.auth import verify_api_key
from video_downloader_api.repositories.job_repo import JobRepository
from video_downloader_api.services.storage_service import StorageService

router = APIRouter(prefix="/files")


@router.get("/{job_id}", dependencies=[Depends(verify_api_key)])
def get_file(job_id: str, db: Session = Depends(get_db)) -> FileResponse:
    """
    Serves completed file for a job_id.
    """
    settings = get_settings()
    repo = JobRepository(db)
    job = repo.get_job(job_id)

    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    if job.status != "finished":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"File not available. Current status: {job.status}",
        )

    storage = StorageService(base_dir=settings.DOWNLOAD_DIR)
    file_path = job.file_path or storage.build_output_path(job_id)

    if not file_path or not os.path.isfile(file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on server.")

    filename = os.path.basename(file_path)
    return FileResponse(path=file_path, filename=filename, media_type="application/octet-stream")
