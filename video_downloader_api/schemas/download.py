# video_downloader_api/schemas/download.py

from __future__ import annotations

from typing import Optional, Union

from pydantic import BaseModel, Field, HttpUrl, field_validator


class ClientCookieSlice(BaseModel):
    """Cookies the phone WebView already has for this site (Codespace has none)."""

    url: str = Field(..., max_length=2048)
    header: str = Field(..., max_length=16384)

    @field_validator("url", "header")
    @classmethod
    def _strip(cls, v: str) -> str:
        return (v or "").strip()


class LinkCheckRequest(BaseModel):
    """
    Request payload used for:
    - POST /download/check
    - POST /download/info
    """

    url: Union[HttpUrl, str] = Field(
        ...,
        description="Video URL pasted by the user (YouTube, Instagram, Facebook, TikTok).",
        examples=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
    )
    client_cookies: Optional[list[ClientCookieSlice]] = Field(
        default=None,
        description="WebView cookie headers from the phone, used when the API host is blocked.",
        max_length=20,
    )


class LinkCheckResponse(BaseModel):
    """
    Response returned after validating a URL.
    """

    valid: bool = Field(..., description="Whether the URL is valid and allowed.")
    platform: str = Field(
        ...,
        description='Detected platform like "youtube", "instagram", "facebook", "tiktok", or "unknown".',
    )
    normalized_url: Optional[str] = Field(
        default=None,
        description="Normalized version of the input URL (if valid).",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Reason why the URL is invalid (only set if valid=false).",
    )


class DownloadStartRequest(BaseModel):
    """
    Request payload used to start a download job.
    """

    url: str = Field(
        ...,
        description="Normalized video URL returned from the info/check endpoint.",
    )
    format_id: str = Field(
        ...,
        description="Format ID chosen from the available formats list.",
    )
    filename_hint: Optional[str] = Field(
        default=None,
        description="Optional filename hint without extension (used if provided).",
    )
    client_cookies: Optional[list[ClientCookieSlice]] = Field(
        default=None,
        description="WebView cookie headers from the phone, used when the API host is blocked.",
        max_length=20,
    )


class DownloadStartResponse(BaseModel):
    """
    Response returned immediately after creating a download job.
    """

    job_id: str = Field(..., description="Unique identifier for the download job.")
    status: str = Field(
        ...,
        description='Initial job status (always "queued").',
        examples=["queued"],
    )
    status_url: str = Field(
        ...,
        description="Endpoint to poll job status.",
        examples=["/api/v1/download/status/abc123"],
    )
    stream_url: str = Field(
        ...,
        description="SSE endpoint for real-time progress updates.",
        examples=["/api/v1/download/stream/abc123"],
    )
    file_url: Optional[str] = Field(
        default=None,
        description="File download URL (available after job finishes).",
    )
