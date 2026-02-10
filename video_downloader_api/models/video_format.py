# video_downloader_api/models/video_format.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class VideoFormat:
    """
    Internal domain model for a single downloadable format.

    This is NOT a Pydantic schema and NOT a DB model.
    It's used inside services/downloader logic (optional).
    """

    format_id: str
    quality: str  # "360p", "720p", etc.
    ext: str  # "mp4", "webm", etc.

    filesize_bytes: Optional[int] = None
    fps: Optional[int] = None
    vcodec: Optional[str] = None
    acodec: Optional[str] = None

    @property
    def is_size_known(self) -> bool:
        return self.filesize_bytes is not None and self.filesize_bytes > 0
