# video_downloader_api/utils/validators.py

from __future__ import annotations

import re
from urllib.parse import urlparse

from fastapi import HTTPException, status


_ALLOWED_SCHEMES = ("http", "https")


def is_valid_url(url: str) -> bool:
    """
    Basic URL validation.
    """
    try:
        u = url.strip()
        if not u.startswith(("http://", "https://")):
            u = "https://" + u
        parsed = urlparse(u)
        return parsed.scheme in _ALLOWED_SCHEMES and bool(parsed.netloc)
    except Exception:
        return False


def extract_domain(url: str) -> str:
    """
    Extract hostname from URL (without www).
    Raises HTTPException if invalid.
    """
    if not is_valid_url(url):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid URL.")

    u = url.strip()
    if not u.startswith(("http://", "https://")):
        u = "https://" + u

    parsed = urlparse(u)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid URL hostname.")
    return host


def is_allowed_domain(domain: str, allowed_domains: list[str]) -> bool:
    """
    Check if domain is allowed by exact match or subdomain.
    """
    d = domain.lower().strip()
    allowed = [x.lower().strip() for x in allowed_domains]
    for a in allowed:
        if d == a or d.endswith("." + a):
            return True
    return False


def validate_format_id(format_id: str) -> None:
    """
    Basic sanity check for format_id to prevent weird injection strings.
    yt-dlp format IDs are usually alphanumeric plus symbols like '-', '_', '.'.
    """
    if not format_id or not isinstance(format_id, str):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="format_id is required.")

    if len(format_id) > 200:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="format_id too long.")

    # allow common yt-dlp format id characters
    if not re.fullmatch(r"[A-Za-z0-9_\-.\+,:/]+", format_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid format_id format.")
