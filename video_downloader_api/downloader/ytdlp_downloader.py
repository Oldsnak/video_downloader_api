# video_downloader_api/downloader/ytdlp_downloader.py

from __future__ import annotations

import os
from logging import Logger
from typing import Any, Callable, Dict, List, Optional

import yt_dlp  # pip install yt-dlp

from video_downloader_api.core.logger import get_logger
from video_downloader_api.downloader.base import BaseDownloader


class YtDlpDownloader(BaseDownloader):
    """
    Concrete downloader implementation using yt-dlp.

    Supports:
    - extract_info(url): fetch metadata without downloading
    - list_formats(info): return available formats
    - download(...): download a chosen format and report progress via callback
    """

    def __init__(self, logger: Optional[Logger] = None) -> None:
        self.logger: Logger = logger or get_logger(self.__class__.__name__)

    def extract_info(self, url: str) -> Dict[str, Any]:
        """
        Calls yt-dlp with download=False to retrieve metadata.

        Returns:
            Raw yt-dlp info dict.
        """
        ydl_opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info or {}
        except Exception as e:
            self.logger.exception("yt-dlp extract_info failed for url=%s", url)
            raise RuntimeError(f"Failed to extract video info: {e}") from e

    def list_formats(self, info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Returns formats list from yt-dlp info dict.
        """
        formats = info.get("formats") or []
        if not isinstance(formats, list):
            return []
        return formats

    def download(
        self,
        url: str,
        format_id: str,
        output_path: str,
        progress_cb: Callable[[Dict[str, Any]], None],
    ) -> str:
        """
        Downloads a specific format using yt-dlp.

        - Uses yt-dlp progress_hooks to call progress_cb(hook_data)
        - Writes the file to output_path

        Returns:
            Final file path (output_path).
        """
        out_dir = os.path.dirname(os.path.abspath(output_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        def _hook(d: Dict[str, Any]) -> None:
            # yt-dlp sends progress updates as dict
            try:
                progress_cb(d)
            except Exception:
                # Do not crash download due to progress callback issues
                self.logger.exception("Progress callback failed (job may still continue).")

        ydl_opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            # Choose exact format:
            "format": format_id,
            # Write exactly to this path:
            "outtmpl": output_path,
            # Progress updates:
            "progress_hooks": [_hook],
            # Reduce noisy files:
            "continuedl": True,
            "retries": 3,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            return output_path
        except Exception as e:
            self.logger.exception("yt-dlp download failed for url=%s format_id=%s", url, format_id)
            raise RuntimeError(f"Failed to download video: {e}") from e
