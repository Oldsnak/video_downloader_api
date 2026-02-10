# video_downloader_api/schemas/video.py

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class VideoFormatOut(BaseModel):
    """
    One downloadable format option for a video.

    This is what your Flutter app will show in a list like:
    - 360p  (167 MB)
    - 720p  (350 MB)
    """

    format_id: str = Field(..., description="Internal format id returned by the downloader (yt-dlp).")
    quality: str = Field(..., description='Video quality label like "360p", "720p", "1080p".')
    ext: str = Field(..., description='File extension like "mp4", "webm".')

    filesize_bytes: Optional[int] = Field(
        default=None,
        description="Exact file size in bytes (if available).",
    )
    filesize_human: Optional[str] = Field(
        default=None,
        description='Human readable file size like "167 MB".',
    )

    fps: Optional[int] = Field(default=None, description="Frames per second if available.")
    vcodec: Optional[str] = Field(default=None, description="Video codec if available.")
    acodec: Optional[str] = Field(default=None, description="Audio codec if available.")


class VideoInfoOut(BaseModel):
    """
    Full metadata response for a given video URL.
    This is returned by: POST /api/v1/download/info
    """

    title: Optional[str] = Field(default=None, description="Video title if available.")
    duration_sec: Optional[int] = Field(default=None, description="Duration in seconds if available.")
    thumbnail: Optional[str] = Field(default=None, description="Thumbnail URL if available.")

    platform: str = Field(..., description='Platform name like "youtube", "instagram", "tiktok".')
    source_url: str = Field(..., description="Normalized input URL.")

    formats: List[VideoFormatOut] = Field(
        default_factory=list,
        description="Available downloadable formats for the video.",
    )
