# video_downloader_api/downloader/base.py

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Any


class BaseDownloader(ABC):
    """
    Standard downloader interface.

    Why this exists:
    - Today you use yt-dlp.
    - Tomorrow you may replace it (or add platform-specific code).
    - Services should not care which downloader is being used.
    """

    @abstractmethod
    def extract_info(self, url: str) -> Dict[str, Any]:
        """
        Fetch video metadata without downloading.

        Args:
            url: Video URL

        Returns:
            Raw info dict (implementation-specific). Services will map this into schemas.
        """
        raise NotImplementedError

    @abstractmethod
    def list_formats(self, info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract a list of available formats from the raw info dict.

        Args:
            info: Raw info dict returned by extract_info()

        Returns:
            List of raw format dictionaries.
        """
        raise NotImplementedError

    @abstractmethod
    def download(
        self,
        url: str,
        format_id: str,
        output_path: str,
        progress_cb: Callable[[Dict[str, Any]], None],
    ) -> str:
        """
        Download a specific format.

        Args:
            url: Video URL
            format_id: Downloader-specific format identifier
            output_path: Final file path to write on disk
            progress_cb: Callback invoked repeatedly with progress hook data

        Returns:
            Final file path (usually output_path).
        """
        raise NotImplementedError
