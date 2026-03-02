# video_downloader_api/services/file_manager.py

from __future__ import annotations

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
        Handles both <job_id>.<ext> and <title>_<job_id>.<ext> naming.
        """
        if not os.path.isdir(base_dir):
            return
        for name in os.listdir(base_dir):
            if job_id not in name:
                continue
            path = os.path.join(base_dir, name)
            if os.path.isfile(path):
                self.delete(path)
