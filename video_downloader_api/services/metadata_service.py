# video_downloader_api/services/metadata_service.py

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from video_downloader_api.core.logger import get_logger
from video_downloader_api.downloader.base import BaseDownloader
from video_downloader_api.schemas.video import VideoInfoOut, VideoFormatOut
from video_downloader_api.services.platform_detector import PlatformDetector
from video_downloader_api.utils.helpers import bytes_to_human, safe_int


def quality_label(fmt: Dict[str, Any]) -> str:
    """
    Build a quality label like 360p, 720p from yt-dlp format dict.
    """
    h = fmt.get("height")
    if isinstance(h, int) and h > 0:
        return f"{h}p"

    # fallback: try format_note or resolution
    note = fmt.get("format_note")
    if note:
        return str(note)

    res = fmt.get("resolution")
    if res:
        return str(res)

    return "unknown"


def _is_storyboard(fmt: Dict[str, Any]) -> bool:
    note = (fmt.get("format_note") or "").strip().lower()
    return note == "storyboard"


def _is_video(fmt: Dict[str, Any]) -> bool:
    return (fmt.get("vcodec") not in (None, "none"))


def _is_audio(fmt: Dict[str, Any]) -> bool:
    return (fmt.get("acodec") not in (None, "none"))


def _is_progressive(fmt: Dict[str, Any]) -> bool:
    """Progressive = video+audio in the same file."""
    return _is_video(fmt) and _is_audio(fmt)


def _resolution_height(fmt: Dict[str, Any]) -> int:
    h = safe_int(fmt.get("height"), default=0) or 0
    return h if h > 0 else 0


def _filesize_bytes(fmt: Dict[str, Any]) -> int | None:
    filesize = fmt.get("filesize") or fmt.get("filesize_approx")
    return safe_int(filesize, default=None)


def _format_sort_score(fmt: Dict[str, Any]) -> tuple:
    """
    Higher score means "better" for selection within the same quality.

    Preference order within the same height:
    1) Progressive (has audio)
    2) mp4 over others (best compatibility for mobile)
    3) larger known filesize (often higher bitrate)
    """
    progressive = 1 if _is_progressive(fmt) else 0
    ext = str(fmt.get("ext") or "").lower().strip()
    is_mp4 = 1 if ext == "mp4" else 0
    size = _filesize_bytes(fmt) or 0
    fps = safe_int(fmt.get("fps"), default=0) or 0
    return (progressive, is_mp4, fps, size)


class MetadataService:
    """
    Given a URL, validate it and return a VideoInfoOut with available formats.

    IMPORTANT:
    We intentionally *do not* return raw yt-dlp formats 1:1.

    YouTube/Instagram often contain:
    - multiple entries for the same resolution
    - video-only formats (no audio) which cause "no voice" downloads

    This service de-duplicates options by quality and prefers progressive (video+audio) formats.
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

    def get_video_info(self, url: str, allowed_domains: List[str]) -> VideoInfoOut:
        """
        Returns clean API response containing video metadata + formats list.

        Strategy:
        - Filter out unusable/storyboard formats
        - Group by height (quality)
        - Within each group pick the best candidate (prefer video+audio)
        """
        platform, normalized_url, info = self.validate_and_extract(url, allowed_domains)

        title = info.get("title")
        duration = info.get("duration")
        thumbnail = info.get("thumbnail")

        raw_formats = self.downloader.list_formats(info)

        # 1) filter
        candidates: List[Dict[str, Any]] = []
        for fmt in raw_formats:
            if not isinstance(fmt, dict):
                continue
            if _is_storyboard(fmt):
                continue

            format_id = fmt.get("format_id")
            if not format_id:
                continue

            # Only keep video formats (yt-dlp also contains audio-only entries)
            if not _is_video(fmt):
                continue

            candidates.append(fmt)

        # 2) group by quality(height)
        by_height: Dict[int, List[Dict[str, Any]]] = {}
        for fmt in candidates:
            h = _resolution_height(fmt)
            # If height unknown, keep it but group under 0; it will appear as "unknown"
            by_height.setdefault(h, []).append(fmt)

        # 3) select best per quality
        selected: List[Dict[str, Any]] = []
        for h, group in by_height.items():
            # Prefer progressive; if none exists, still return best video-only option,
            # but format_id will likely produce no-audio downloads unless we later merge.
            # (We will address merge in the downloader step.)
            group_sorted = sorted(group, key=_format_sort_score, reverse=True)
            best = group_sorted[0]
            selected.append(best)

        # 4) map to API schema
        formats_out: List[VideoFormatOut] = []
        for fmt in selected:
            format_id = str(fmt.get("format_id"))
            vcodec = fmt.get("vcodec")
            acodec = fmt.get("acodec")
            ext = fmt.get("ext") or "mp4"

            filesize_bytes = _filesize_bytes(fmt)

            formats_out.append(
                VideoFormatOut(
                    format_id=format_id,
                    quality=quality_label(fmt),
                    ext=str(ext),
                    filesize_bytes=filesize_bytes,
                    filesize_human=bytes_to_human(filesize_bytes),
                    fps=safe_int(fmt.get("fps"), default=None),
                    vcodec=str(vcodec) if vcodec else None,
                    acodec=str(acodec) if acodec else None,
                )
            )

        # Sort by numeric quality when possible: 360p < 720p < 1080p
        def _sort_key(v: VideoFormatOut) -> int:
            q = (v.quality or "").lower().strip()
            if q.endswith("p"):
                return safe_int(q[:-1], default=0) or 0
            return 0

        formats_out.sort(key=_sort_key)

        return VideoInfoOut(
            title=str(title) if title else None,
            duration_sec=safe_int(duration, default=None),
            thumbnail=str(thumbnail) if thumbnail else None,
            platform=platform,
            source_url=normalized_url,
            formats=formats_out,
        )
