# video_downloader_api/models/video_info.py

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from video_downloader_api.models.video_format import VideoFormat


@dataclass(frozen=True)
class VideoInfo:
    """
    Internal domain model for complete video metadata.

    This is separate from schemas.VideoInfoOut (API response).
    """

    source_url: str
    platform: str  # "youtube"/"instagram"/...
    title: Optional[str] = None
    duration_sec: Optional[int] = None
    thumbnail: Optional[str] = None
    formats: List[VideoFormat] = None

    def __post_init__(self):
        # dataclass with default None list is unsafe; normalize it.
        if self.formats is None:
            object.__setattr__(self, "formats", [])
