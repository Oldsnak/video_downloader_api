# video_downloader_api/services/client_cookies.py

from __future__ import annotations

import os
import re
import tempfile
from typing import Iterable, Optional, Sequence
from urllib.parse import urlparse

from video_downloader_api.core.config import get_settings

_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+\-.^_`|~]+$")


def job_cookie_path(job_id: str) -> str:
    settings = get_settings()
    return os.path.join(settings.DOWNLOAD_DIR, ".client_cookies", f"{job_id}.txt")


def persist_client_cookies(job_id: str, slices: Optional[Sequence[object]]) -> Optional[str]:
    path = job_cookie_path(job_id)
    if not write_netscape_file(path, slices):
        return None
    return path


def write_temp_netscape(slices: Optional[Sequence[object]]) -> Optional[str]:
    if not slices:
        return None
    fd, path = tempfile.mkstemp(prefix="client_cookies_", suffix=".txt")
    os.close(fd)
    if not write_netscape_file(path, slices):
        try:
            os.remove(path)
        except OSError:
            pass
        return None
    return path


def remove_cookie_file(path: Optional[str]) -> None:
    if not path:
        return
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def remove_job_cookies(job_id: str) -> None:
    remove_cookie_file(job_cookie_path(job_id))


def write_netscape_file(path: str, slices: Optional[Sequence[object]]) -> bool:
    """Write a Netscape cookies.txt. Returns False when there is nothing to write."""
    lines = ["# Netscape HTTP Cookie File", ""]
    wrote = False
    for url, header in _iter_slices(slices):
        host = (urlparse(url).hostname or "").lower().strip(".")
        if not host or not header:
            continue
        if host.startswith("www."):
            domain = "." + host[4:]
        else:
            domain = "." + host
        secure = "TRUE" if (urlparse(url).scheme or "https").lower() == "https" else "FALSE"
        for name, value in _parse_cookie_header(header):
            lines.append(f"{domain}\tTRUE\t/\t{secure}\t0\t{name}\t{value}")
            wrote = True
    if not wrote:
        return False
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return True


def _iter_slices(slices: Optional[Sequence[object]]) -> Iterable[tuple[str, str]]:
    if not slices:
        return
    for item in slices:
        if item is None:
            continue
        if isinstance(item, dict):
            url = str(item.get("url") or "")
            header = str(item.get("header") or "")
        else:
            url = str(getattr(item, "url", "") or "")
            header = str(getattr(item, "header", "") or "")
        url = url.strip()
        header = header.strip()
        if url and header:
            yield url, header


def _parse_cookie_header(header: str) -> Iterable[tuple[str, str]]:
    for part in header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name, value = name.strip(), value.strip()
        if not name or not _HEADER_NAME_RE.match(name):
            continue
        if name.lower() in {"httponly", "secure", "path", "domain", "expires", "max-age", "samesite"}:
            continue
        if "\n" in name or "\n" in value or "\r" in name or "\r" in value:
            continue
        yield name, value
