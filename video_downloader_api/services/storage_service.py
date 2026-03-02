# video_downloader_api/services/storage_service.py

from __future__ import annotations

import os
import re
from typing import Optional

from video_downloader_api.core.config import get_settings

_VIDEO_EXTENSIONS = (".mp4", ".mkv", ".webm", ".m4a", ".opus")


def _sanitize_filename_part(title: Optional[str], max_length: int = 120) -> Optional[str]:
    """Make a safe filename fragment from video title (no path chars, length limited)."""
    if not title or not title.strip():
        return None
    s = title.strip()
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", s)
    s = re.sub(r"\s+", " ", s)
    s = s.strip()
    if not s:
        return None
    if len(s) > max_length:
        s = s[:max_length].strip()
    return s if s else None


class StorageService:
    """
    Generates file paths and public URLs for completed downloads.
    """

    def __init__(self, base_dir: str) -> None:
        self.base_dir = os.path.abspath(base_dir)
        self.settings = get_settings()

    def ensure_dirs(self) -> None:
        """
        Ensure the downloads directory exists.
        """
        os.makedirs(self.base_dir, exist_ok=True)

    def build_output_path(
        self,
        job_id: str,
        ext: str = "mp4",
        title: Optional[str] = None,
    ) -> str:
        """
        Build a stable output path for a job.
        If title is provided, filename is <sanitized_title>_<job_id>.<ext>, else <job_id>.<ext>.
        """
        self.ensure_dirs()
        safe_ext = (ext or "mp4").lstrip(".").strip() or "mp4"
        safe_title = _sanitize_filename_part(title)
        if safe_title:
            filename = f"{safe_title}_{job_id}.{safe_ext}"
        else:
            filename = f"{job_id}.{safe_ext}"
        return os.path.abspath(os.path.join(self.base_dir, filename))

    def find_file_by_job_id(self, job_id: str) -> Optional[str]:
        """
        Scan the download directory for a file that belongs to this job.
        Matches: <job_id>.<ext>, <title>_<job_id>.<ext>, or any name containing job_id.
        """
        if not job_id or not os.path.isdir(self.base_dir):
            return None
        exact = self.build_output_path(job_id, "mp4")
        if os.path.isfile(exact):
            return exact
        for name in os.listdir(self.base_dir):
            if job_id not in name:
                continue
            lower = name.lower()
            if any(lower.endswith(ext) for ext in _VIDEO_EXTENSIONS):
                path = os.path.join(self.base_dir, name)
                if os.path.isfile(path):
                    return os.path.abspath(path)
        return None

    def public_url_for(self, job_id: str) -> Optional[str]:
        """
        Build a public URL to download the file via API.

        This assumes you have:
            GET /api/v1/files/{job_id}

        If you want to disable public URL generation, return None.
        """
        # if API prefix changes, this always stays correct
        return f"{self.settings.API_V1_PREFIX}/files/{job_id}"
