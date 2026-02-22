# video_downloader_api/api/v1/routes/files.py

from __future__ import annotations

import os
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from video_downloader_api.core.config import get_settings
from video_downloader_api.db.session import get_db
from video_downloader_api.middleware.auth import verify_api_key
from video_downloader_api.repositories.job_repo import JobRepository
from video_downloader_api.services.storage_service import StorageService

router = APIRouter(prefix="/files")

CHUNK_SIZE = 1024 * 1024  # 1 MB


def _stream_and_cleanup(file_path: str, delete_after: bool) -> Iterator[bytes]:
    """Yield file chunks; optionally delete file after stream."""
    try:
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
    finally:
        if delete_after and file_path and os.path.isfile(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass


@router.get("/{job_id}", dependencies=[Depends(verify_api_key)])
def get_file(job_id: str, db: Session = Depends(get_db)):
    """
    Streams the completed download file to the client (e.g. Flutter). Client should
    save the response to device storage. When DELETE_FILE_AFTER_STREAM is True (SaaS),
    the file is removed from the server after a successful stream.
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
    media_type = "application/octet-stream"

    if settings.DELETE_FILE_AFTER_STREAM:
        size = os.path.getsize(file_path)
        return StreamingResponse(
            _stream_and_cleanup(file_path, delete_after=True),
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(size),
            },
        )

    return FileResponse(path=file_path, filename=filename, media_type=media_type)
