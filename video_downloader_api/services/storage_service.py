# video_downloader_api/services/storage_service.py

from __future__ import annotations

import os
from typing import Optional

from video_downloader_api.core.config import get_settings


class StorageService:
    """
    Generates file paths and public URLs for completed downloads.
    """

    def __init__(self, base_dir: str) -> None:
        self.base_dir = base_dir
        self.settings = get_settings()

    def ensure_dirs(self) -> None:
        """
        Ensure the downloads directory exists.
        """
        os.makedirs(self.base_dir, exist_ok=True)

    def build_output_path(self, job_id: str, ext: str = "mp4") -> str:
        """
        Build a stable output path for a job.

        Example:
            downloads/<job_id>.mp4
        """
        self.ensure_dirs()
        safe_ext = (ext or "mp4").lstrip(".").strip() or "mp4"
        filename = f"{job_id}.{safe_ext}"
        return os.path.join(self.base_dir, filename)

    def public_url_for(self, job_id: str) -> Optional[str]:
        """
        Build a public URL to download the file via API.

        This assumes you have:
            GET /api/v1/files/{job_id}

        If you want to disable public URL generation, return None.
        """
        # if API prefix changes, this always stays correct
        return f"{self.settings.API_V1_PREFIX}/files/{job_id}"
