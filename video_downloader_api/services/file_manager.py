# video_downloader_api/services/file_manager.py

from __future__ import annotations

import glob
import os


class FileManager:
    """
    Low-level file operations (exists/delete/cleanup).
    """

    def exists(self, path: str) -> bool:
        return os.path.exists(path)

    def delete(self, path: str) -> None:
        """
        Delete a file safely (ignore if missing).
        """
        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            # We intentionally ignore delete failures (permissions, locks, etc.)
            pass

    def cleanup_job_files(self, job_id: str, base_dir: str) -> None:
        """
        Cleanup leftover / partial files for a job.

        yt-dlp and related tools may create temp files like:
        - <job_id>.part
        - <job_id>.temp
        - <job_id>.ytdl
        - and other fragments

        We'll delete any file matching: base_dir/<job_id>.*
        """
        pattern = os.path.join(base_dir, f"{job_id}.*")
        for path in glob.glob(pattern):
            self.delete(path)
