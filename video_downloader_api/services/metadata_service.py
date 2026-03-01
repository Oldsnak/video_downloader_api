# video_downloader_api/services/metadata_service.py

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from video_downloader_api.core.logger import get_logger
from video_downloader_api.downloader.base import BaseDownloader
from video_downloader_api.schemas.video import PlaylistInfoOut, VideoFormatOut, VideoInfoOut
from video_downloader_api.services.platform_detector import PlatformDetector
from video_downloader_api.utils.helpers import bytes_to_human, safe_int


def quality_label_from_height(height: Optional[int]) -> str:
    """Build quality label like 360p, 720p from height.".\.venv\Scripts\activate"""
    if isinstance(height, int) and height > 0:
        return f"{height}p"
    return "unknown"


def _height(fmt: Dict[str, Any]) -> Optional[int]:
    """Extract height from format dict."""
    h = fmt.get("height")
    return safe_int(h, default=None) if h is not None else None


def _has_video(fmt: Dict[str, Any]) -> bool:
    vcodec = fmt.get("vcodec")
    return vcodec is not None and str(vcodec).lower() != "none"


def _has_audio(fmt: Dict[str, Any]) -> bool:
    acodec = fmt.get("acodec")
    return acodec is not None and str(acodec).lower() != "none"


def _is_merged(fmt: Dict[str, Any]) -> bool:
    """True if this format has both video and audio (single file)."""
    return _has_video(fmt) and _has_audio(fmt)


class MetadataService:
    """
    Given a URL, validate it and return a VideoInfoOut with available formats.
    """

    def __init__(self, downloader: BaseDownloader, detector: PlatformDetector) -> None:
        self.downloader = downloader
        self.detector = detector
        self.logger = get_logger(self.__class__.__name__)

    def validate_and_extract(self, url: str, allowed_domains: List[str]) -> Tuple[str, str, Dict[str, Any]]:
        """
        Pipeline:
        - normalize url
        - check allowlist
        - detect platform
        - call downloader.extract_info(normalized_url)

        Returns:
            (platform, normalized_url, info_dict)
        """
        normalized = self.detector.normalize_url(url)

        if not self.detector.is_allowed_domain(normalized, allowed_domains):
            raise ValueError("Domain is not allowed.")

        platform = self.detector.detect_platform(normalized)
        info = self.downloader.extract_info(normalized)
        return platform, normalized, info

    def validate_and_extract_playlist(
        self, url: str, allowed_domains: List[str]
    ) -> Tuple[str, str, Dict[str, Any]]:
        """
        Same as [validate_and_extract] but keeps playlist structure (no noplaylist)
        so that we can list all entries for a playlist URL.
        """
        normalized = self.detector.normalize_url(url)

        if not self.detector.is_allowed_domain(normalized, allowed_domains):
            raise ValueError("Domain is not allowed.")

        platform = self.detector.detect_platform(normalized)
        info = self.downloader.extract_playlist(normalized)
        return platform, normalized, info

    def get_video_info(self, url: str, allowed_domains: List[str]) -> VideoInfoOut:
        """
        Returns clean API response containing video metadata + one format per quality.
        Deduplicates YouTube/Instagram formats (no more 3 sizes per 720p). Prefers
        merged (video+audio) formats; for separate streams we use format_id = height
        so the downloader merges bestvideo+bestaudio at download time.
        """
        platform, normalized_url, info = self.validate_and_extract(url, allowed_domains)

        title = info.get("title")
        duration = info.get("duration")
        thumbnail = info.get("thumbnail")

        raw_formats = self.downloader.list_formats(info)

        # Group by height (resolution). For each height keep at most one format:
        # prefer merged (video+audio), then video-only (we'll merge at download time).
        # Key: height (int), Value: (format_dict, is_merged)
        by_height: Dict[int, Tuple[Dict[str, Any], bool]] = {}

        for fmt in raw_formats:
            if not isinstance(fmt, dict):
                continue
            if not _has_video(fmt):
                continue
            if fmt.get("format_note") == "storyboard":
                continue

            height = _height(fmt)
            if height is None or height <= 0:
                continue

            merged = _is_merged(fmt)
            existing = by_height.get(height)
            # Prefer merged (video+audio) over video-only
            if existing is not None:
                existing_merged = existing[1]
                if existing_merged and not merged:
                    continue  # keep existing merged
                if not existing_merged and merged:
                    by_height[height] = (fmt, merged)  # replace with merged
                # else keep existing (both merged or both video-only)
                continue
            by_height[height] = (fmt, merged)

        formats_out: List[VideoFormatOut] = []
        for height in sorted(by_height.keys()):
            fmt, _ = by_height[height]
            quality = quality_label_from_height(height)
            # Use height as format_id so downloader can use bestvideo[height<=H]+bestaudio
            format_id = str(height)
            ext = fmt.get("ext") or "mp4"
            vcodec = fmt.get("vcodec")
            acodec = fmt.get("acodec")
            filesize = fmt.get("filesize") or fmt.get("filesize_approx")
            filesize_bytes = safe_int(filesize, default=None)

            formats_out.append(
                VideoFormatOut(
                    format_id=format_id,
                    quality=quality,
                    ext=str(ext),
                    filesize_bytes=filesize_bytes,
                    filesize_human=bytes_to_human(filesize_bytes),
                    fps=safe_int(fmt.get("fps"), default=None),
                    vcodec=str(vcodec) if vcodec else None,
                    acodec=str(acodec) if acodec else None,
                )
            )

        # Add "best" option (let yt-dlp choose)
        formats_out.insert(
            0,
            VideoFormatOut(
                format_id="best",
                quality="best",
                ext="mp4",
                filesize_bytes=None,
                filesize_human=None,
                fps=None,
                vcodec=None,
                acodec=None,
            ),
        )

        return VideoInfoOut(
            title=str(title) if title else None,
            duration_sec=safe_int(duration, default=None),
            thumbnail=str(thumbnail) if thumbnail else None,
            platform=platform,
            source_url=normalized_url,
            formats=formats_out,
        )

    def get_playlist_info(self, url: str, allowed_domains: List[str]) -> PlaylistInfoOut:
        """
        Returns metadata for all videos in a playlist URL.
        Internally reuses [get_video_info] for each entry so the response shape
        matches the single-video API (VideoInfoOut per item).
        """
        platform, normalized_url, info = self.validate_and_extract_playlist(url, allowed_domains)

        title = info.get("title")
        entries = info.get("entries") or []
        videos: List[VideoInfoOut] = []

        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                entry_url = entry.get("url") or entry.get("webpage_url")
                if not entry_url:
                    continue
                try:
                    vinfo = self.get_video_info(str(entry_url), allowed_domains)
                    videos.append(vinfo)
                except Exception:
                    self.logger.exception(
                        "Failed to build VideoInfoOut for playlist entry url=%s", entry_url
                    )
                    continue

        return PlaylistInfoOut(
            title=str(title) if title else None,
            playlist_url=normalized_url,
            videos=videos,
        )
