# video_downloader_api/utils/helpers.py

from __future__ import annotations

from typing import Optional


def bytes_to_human(num_bytes: Optional[int]) -> Optional[str]:
    """
    Convert bytes to a human-readable string.
    Examples:
      900 -> "900 B"
      1500 -> "1.5 KB"
      1048576 -> "1.0 MB"
    """
    if num_bytes is None:
        return None
    try:
        n = int(num_bytes)
    except Exception:
        return None

    if n < 0:
        n = 0

    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(n)
    idx = 0

    while size >= 1024 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1

    if idx == 0:
        return f"{int(size)} {units[idx]}"
    if size >= 10:
        return f"{size:.0f} {units[idx]}"
    return f"{size:.1f} {units[idx]}"


def safe_int(value, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return default


def safe_float(value, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return default
