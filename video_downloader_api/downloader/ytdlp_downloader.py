# video_downloader_api/downloader/ytdlp_downloader.py

from __future__ import annotations

import os
import re
from logging import Logger
from typing import Any, Callable, Dict, List, Optional

import yt_dlp  # pip install yt-dlp

from video_downloader_api.core.logger import get_logger
from video_downloader_api.downloader.base import BaseDownloader

# Quality format_id from our API: "best" or numeric "144", "720", "1080" (optionally "720p")
_QUALITY_PATTERN = re.compile(r"^(?:best|\d+p?)$", re.IGNORECASE)


def _format_selector(format_id: str) -> str:
    """
    Build yt-dlp format string so we get video+audio (merged). Avoids video-only
    formats that cause no-audio or corrupted files on YouTube/Instagram.
    - "best" -> bestvideo+bestaudio/best
    - "720" or "720p" -> bestvideo[height<=720]+bestaudio/best[height<=720]
    """
    format_id = (format_id or "").strip()
    if not format_id or format_id.lower() == "best":
        return "bestvideo+bestaudio/best"

    match = re.match(r"^(\d+)p?$", format_id, re.IGNORECASE)
    if match:
        height = match.group(1)
        # Prefer same resolution; merge best video up to height + best audio
        return f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"

    # Unknown (e.g. TikTok single-format id): use as-is; may be a single stream
    return format_id


def _is_quality_selector(format_id: str) -> bool:
    """True if format_id is our quality token (best or height) that needs merge."""
    if not format_id or not isinstance(format_id, str):
        return False
    return bool(_QUALITY_PATTERN.match(format_id.strip()))


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

    def extract_playlist(self, url: str) -> Dict[str, Any]:
        """
        Extract high-level playlist information (entries) without downloading.
        Used for playlist metadata; does not change single-video behavior.
        """
        ydl_opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": False,
            "extract_flat": True,
            "skip_download": True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info or {}
        except Exception as e:
            self.logger.exception("yt-dlp extract_playlist failed for url=%s", url)
            raise RuntimeError(f"Failed to extract playlist info: {e}") from e

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
        Downloads a specific format using yt-dlp. For quality-based ids (e.g. "720",
        "best") uses merged bestvideo+bestaudio so output has both video and audio.
        """
        out_dir = os.path.dirname(os.path.abspath(output_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        def _hook(d: Dict[str, Any]) -> None:
            try:
                progress_cb(d)
            except Exception:
                self.logger.exception("Progress callback failed (job may still continue).")

        format_selector = _format_selector(format_id)
        use_merge = _is_quality_selector(format_id)

        ydl_opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": format_selector,
            "outtmpl": output_path,
            "progress_hooks": [_hook],
            "continuedl": True,
            "retries": 3,
        }

        if use_merge:
            # Ensure merged output is mp4 (fixes corruption/container issues)
            ydl_opts["postprocessors"] = [
                {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"},
            ]

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            return output_path
        except Exception as e:
            self.logger.exception("yt-dlp download failed for url=%s format_id=%s", url, format_id)
            raise RuntimeError(f"Failed to download video: {e}") from e