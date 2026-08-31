# video_downloader_api/api/v1/routes/files.py

from __future__ import annotations

import os
import re
from typing import Iterator, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from video_downloader_api.core.config import get_settings
from video_downloader_api.core.logger import get_logger
from video_downloader_api.db.session import get_db
from video_downloader_api.middleware.auth import verify_api_key
from video_downloader_api.repositories.job_repo import JobRepository
from video_downloader_api.services.storage_service import StorageService

router = APIRouter(prefix="/files")
logger = get_logger("files.route")

CHUNK_SIZE = 1024 * 1024  # 1 MB


_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")

# Spelled out because starlette renamed its constant across versions.
_HTTP_416_RANGE_NOT_SATISFIABLE = 416


def _parse_range_header(range_header: Optional[str], file_size: int) -> Optional[Tuple[int, int]]:
    """Parse a single-range `Range` header into an inclusive (start, end) pair.

    Returns None for absent/unsupported headers so the caller falls back to a full
    200 response. Raises 416 for a syntactically valid but unsatisfiable range.
    """
    if not range_header or file_size <= 0:
        return None

    match = _RANGE_RE.match(range_header.strip())
    if not match:
        return None

    raw_start, raw_end = match.group(1), match.group(2)

    if raw_start == "":
        if raw_end == "":
            return None
        # Suffix form: last N bytes.
        suffix = int(raw_end)
        if suffix <= 0:
            raise HTTPException(
                status_code=_HTTP_416_RANGE_NOT_SATISFIABLE,
                detail="Invalid range.",
                headers={"Content-Range": f"bytes */{file_size}"},
            )
        start = max(file_size - suffix, 0)
        end = file_size - 1
    else:
        start = int(raw_start)
        end = int(raw_end) if raw_end != "" else file_size - 1

    end = min(end, file_size - 1)

    if start > end or start >= file_size:
        raise HTTPException(
            status_code=_HTTP_416_RANGE_NOT_SATISFIABLE,
            detail="Requested range not satisfiable.",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    return start, end


def _stream_range(
    file_path: str,
    start: int,
    end: int,
    delete_when_complete: bool,
) -> Iterator[bytes]:
    """Yield bytes [start, end] inclusive.

    The file is deleted only when every requested byte was handed to the transport.
    A client that disconnects mid-stream (phone screen off, app backgrounded) raises
    GeneratorExit inside the loop, so `served_all` stays False and the file survives
    for the client to resume or retry.
    """
    served_all = False
    try:
        remaining = end - start + 1
        with open(file_path, "rb") as f:
            f.seek(start)
            while remaining > 0:
                chunk = f.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
        served_all = remaining <= 0
    finally:
        if served_all and delete_when_complete and file_path and os.path.isfile(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass


def _content_disposition(filename: str) -> str:
    """Attachment header with both a plain and an RFC 5987 encoded filename."""
    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii").replace('"', "") or "video.mp4"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"


@router.get("/{job_id}", dependencies=[Depends(verify_api_key)])
def get_file(job_id: str, request: Request, db: Session = Depends(get_db)):
    """
    Streams the completed download file to the client (e.g. Flutter). Client should
    save the response to device storage. Supports HTTP Range so an interrupted
    transfer can be resumed instead of restarted. When DELETE_FILE_AFTER_STREAM is
    True (SaaS), the file is removed only once the client has received it fully.
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
    file_path = os.path.normpath(os.path.abspath(file_path)) if file_path else None

    if not file_path or not os.path.isfile(file_path):
        # Fallback 1: try default path (downloads/<job_id>.mp4)
        fallback_path = storage.build_output_path(job_id)
        if os.path.isfile(fallback_path):
            logger.info("get_file: job_id=%s served from fallback path; db_path=%s", job_id, job.file_path)
            file_path = fallback_path
            try:
                repo.set_file(
                    job_id=job_id,
                    file_path=file_path,
                    public_url=storage.public_url_for(job_id),
                )
            except Exception as e:
                logger.warning("get_file: could not update job file_path for job_id=%s: %s", job_id, e)
        else:
            # Fallback 2: scan download dir for any file matching job_id (yt-dlp may use different name)
            file_path = storage.find_file_by_job_id(job_id)
            if file_path:
                logger.info(
                    "get_file: job_id=%s served from scan; db_path=%s found=%s",
                    job_id, job.file_path, file_path,
                )
                try:
                    repo.set_file(
                        job_id=job_id,
                        file_path=file_path,
                        public_url=storage.public_url_for(job_id),
                    )
                except Exception as e:
                    logger.warning("get_file: could not update job file_path for job_id=%s: %s", job_id, e)
            else:
                logger.warning(
                    "get_file: job_id=%s file not found; db_path=%s resolved=%s fallback_path=%s",
                    job_id, job.file_path, file_path, fallback_path,
                )
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on server.")

    filename = os.path.basename(file_path)
    media_type = "application/octet-stream"
    file_size = os.path.getsize(file_path)

    byte_range = _parse_range_header(request.headers.get("range"), file_size)
    start, end = byte_range if byte_range else (0, max(file_size - 1, 0))

    # Only drop the file once the client has been served through the last byte;
    # a partial range means the client still needs the rest.
    delete_when_complete = settings.DELETE_FILE_AFTER_STREAM and end == file_size - 1

    headers = {
        "Content-Disposition": _content_disposition(filename),
        "Content-Length": str(end - start + 1 if file_size else 0),
        "Accept-Ranges": "bytes",
    }
    if byte_range:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"

    return StreamingResponse(
        _stream_range(file_path, start, end, delete_when_complete=delete_when_complete),
        status_code=status.HTTP_206_PARTIAL_CONTENT if byte_range else status.HTTP_200_OK,
        media_type=media_type,
        headers=headers,
    )
