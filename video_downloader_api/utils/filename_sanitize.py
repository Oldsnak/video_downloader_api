# video_downloader_api/utils/filename_sanitize.py
"""Sanitize video download basenames for cross-platform and mobile-safe paths."""

from __future__ import annotations

import re
import secrets
from typing import Optional

# Allowed in the human-readable stem (before random suffix + job id): letters, digits, # $ _ -
_ALLOWED_STEM_RE = re.compile(r"[a-zA-Z0-9#\$_-]")
_MAX_TITLE_STEM_LEN = 100


def _random_digit_suffix(min_len: int = 9, max_len: int = 12) -> str:
    """Return a string of `min_len`..`max_len` random decimal digits."""
    n = min_len + secrets.randbelow(max_len - min_len + 1)
    return "".join(secrets.choice("0123456789") for _ in range(n))


def sanitize_download_stem(title: str, max_length: int = _MAX_TITLE_STEM_LEN) -> str:
    """
    Replace any character not in [a-zA-Z0-9#$_-] with '_', collapse underscores,
    trim, and cap length (before extension — caller must not pass an extension).
    """
    if not title or not str(title).strip():
        return "video"
    s = str(title).strip()
    parts: list[str] = []
    for ch in s:
        parts.append(ch if _ALLOWED_STEM_RE.match(ch) else "_")
    out = "".join(parts)
    out = re.sub(r"_+", "_", out).strip("_")
    if not out:
        out = "video"
    if len(out) > max_length:
        out = out[:max_length].rstrip("_")
    if not out:
        out = "video"
    return out


def build_download_basename(job_id: str, ext: str, title: Optional[str] = None) -> str:
    """
    Build a safe filename: {stem}_{9-12 random digits}_{job_id}.{ext}
    If title is missing, {job_id}.{ext}.
    """
    safe_ext = (ext or "mp4").lstrip(".").strip() or "mp4"
    if not job_id or not str(job_id).strip():
        raise ValueError("job_id is required")
    jid = str(job_id).strip()
    if not title or not str(title).strip():
        return f"{jid}.{safe_ext}"
    stem = sanitize_download_stem(title)
    rnd = _random_digit_suffix()
    return f"{stem}_{rnd}_{jid}.{safe_ext}"
