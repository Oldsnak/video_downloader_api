# video_downloader_api/middleware/auth.py

from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException, status

from video_downloader_api.core.config import get_settings


def verify_api_key(x_api_key: Optional[str] = Header(default=None, alias="X-API-KEY")) -> None:
    """
    Simple API key protection.

    If settings.API_KEY is set:
      - requires X-API-KEY header to match
    If settings.API_KEY is None:
      - allows all requests (dev mode)
    """
    settings = get_settings()

    # If no API key configured, skip auth
    if not settings.API_KEY:
        return

    if not x_api_key or x_api_key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )
