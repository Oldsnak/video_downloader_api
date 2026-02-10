# video_downloader_api/schemas/status.py

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ProgressOut(BaseModel):
    """
    Progress information for a running download.
    """

    downloaded_bytes: int = Field(..., description="Bytes downloaded so far.")
    total_bytes: Optional[int] = Field(default=None, description="Total bytes if known.")
    speed_bps: Optional[float] = Field(default=None, description="Download speed in bytes per second.")
    eta_sec: Optional[int] = Field(default=None, description="Estimated time remaining in seconds.")
    percent: Optional[float] = Field(default=None, description="Progress percentage (0-100) if total size is known.")


class JobStatusOut(BaseModel):
    """
    Complete job status returned to the client (Flutter).
    """

    job_id: str = Field(..., description="Unique identifier for this job.")
    status: str = Field(..., description='Job status like "queued", "downloading", "finished", "failed", "canceled".')
    platform: str = Field(..., description='Platform like "youtube", "instagram", "facebook", "tiktok", "unknown".')
    source_url: str = Field(..., description="Normalized source URL.")

    format_id: Optional[str] = Field(default=None, description="Selected format id if provided.")
    quality: Optional[str] = Field(default=None, description='Selected quality label like "720p".')

    progress: Optional[ProgressOut] = Field(default=None, description="Progress details if downloading.")
    file_path: Optional[str] = Field(default=None, description="Local path to downloaded file (server-side).")
    public_url: Optional[str] = Field(default=None, description="Public URL to download the file from this API.")
    error: Optional[str] = Field(default=None, description="Error message if job failed.")

    created_at: datetime = Field(..., description="Job creation timestamp (UTC).")
    updated_at: datetime = Field(..., description="Last update timestamp (UTC).")
