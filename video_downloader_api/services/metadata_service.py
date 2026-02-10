# # video_downloader_api/services/metadata_service.py
#
# from __future__ import annotations
#
# from typing import Any, Dict, List, Tuple
#
# from core.logger import get_logger
# from downloader.base import BaseDownloader
# from schemas.video import VideoInfoOut, VideoFormatOut
# from services.platform_detector import PlatformDetector
#
#
# def human_size(num_bytes: int) -> str:
#     """
#     Convert bytes to human-readable size string.
#     Example: 167 MB, 1.2 GB, 900 KB
#     """
#     if num_bytes < 0:
#         num_bytes = 0
#
#     units = ["B", "KB", "MB", "GB", "TB"]
#     size = float(num_bytes)
#     idx = 0
#     while size >= 1024 and idx < len(units) - 1:
#         size /= 1024.0
#         idx += 1
#
#     if idx == 0:
#         return f"{int(size)} {units[idx]}"
#     if size >= 10:
#         return f"{size:.0f} {units[idx]}"
#     return f"{size:.1f} {units[idx]}"
#
#
# def quality_label(fmt: Dict[str, Any]) -> str:
#     """
#     Build a quality label like 360p, 720p from yt-dlp format dict.
#     """
#     h = fmt.get("height")
#     if isinstance(h, int) and h > 0:
#         return f"{h}p"
#     # fallback: try format_note or resolution
#     note = fmt.get("format_note")
#     if note:
#         return str(note)
#     res = fmt.get("resolution")
#     if res:
#         return str(res)
#     return "unknown"
#
#
# class MetadataService:
#     """
#     Given a URL, validate it and return a VideoInfoOut with available formats.
#     """
#
#     def __init__(self, downloader: BaseDownloader, detector: PlatformDetector) -> None:
#         self.downloader = downloader
#         self.detector = detector
#         self.logger = get_logger(self.__class__.__name__)
#
#     def validate_and_extract(self, url: str, allowed_domains: List[str]) -> Tuple[str, str, Dict[str, Any]]:
#         """
#         Pipeline:
#         - normalize url
#         - check allowlist
#         - detect platform
#         - call downloader.extract_info(normalized_url)
#
#         Returns:
#             (platform, normalized_url, info_dict)
#         """
#         normalized = self.detector.normalize_url(url)
#
#         if not self.detector.is_allowed_domain(normalized, allowed_domains):
#             raise ValueError("Domain is not allowed.")
#
#         platform = self.detector.detect_platform(normalized)
#         info = self.downloader.extract_info(normalized)
#         return platform, normalized, info
#
#     def get_video_info(self, url: str, allowed_domains: List[str]) -> VideoInfoOut:
#         """
#         Returns clean API response containing video metadata + formats list with sizes.
#         """
#         platform, normalized_url, info = self.validate_and_extract(url, allowed_domains)
#
#         title = info.get("title")
#         duration = info.get("duration")
#         thumbnail = info.get("thumbnail")
#
#         raw_formats = self.downloader.list_formats(info)
#
#         # Filter to "video formats" primarily (avoid pure audio-only by default)
#         formats_out: List[VideoFormatOut] = []
#
#         for fmt in raw_formats:
#             if not isinstance(fmt, dict):
#                 continue
#
#             format_id = fmt.get("format_id")
#             ext = fmt.get("ext") or "mp4"
#             vcodec = fmt.get("vcodec")
#             acodec = fmt.get("acodec")
#
#             # Skip formats with no video (audio-only)
#             if vcodec in (None, "none"):
#                 continue
#
#             # filesize may be in different keys
#             filesize = fmt.get("filesize") or fmt.get("filesize_approx")
#             filesize_bytes = int(filesize) if isinstance(filesize, (int, float)) else None
#
#             formats_out.append(
#                 VideoFormatOut(
#                     format_id=str(format_id) if format_id is not None else "",
#                     quality=quality_label(fmt),
#                     ext=str(ext),
#                     filesize_bytes=filesize_bytes,
#                     filesize_human=human_size(filesize_bytes) if filesize_bytes is not None else None,
#                     fps=fmt.get("fps") if isinstance(fmt.get("fps"), int) else None,
#                     vcodec=str(vcodec) if vcodec else None,
#                     acodec=str(acodec) if acodec else None,
#                 )
#             )
#
#         # Sort by quality if possible (height)
#         def _sort_key(v: VideoFormatOut) -> int:
#             try:
#                 return int(v.quality.replace("p", ""))
#             except Exception:
#                 return 0
#
#         formats_out.sort(key=_sort_key)
#
#         return VideoInfoOut(
#             title=str(title) if title else None,
#             duration_sec=int(duration) if isinstance(duration, (int, float)) else None,
#             thumbnail=str(thumbnail) if thumbnail else None,
#             platform=platform,
#             source_url=normalized_url,
#             formats=formats_out,
#         )



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

    def get_video_info(self, url: str, allowed_domains: List[str]) -> VideoInfoOut:
        """
        Returns clean API response containing video metadata + formats list with sizes.
        """
        platform, normalized_url, info = self.validate_and_extract(url, allowed_domains)

        title = info.get("title")
        duration = info.get("duration")
        thumbnail = info.get("thumbnail")

        raw_formats = self.downloader.list_formats(info)

        formats_out: List[VideoFormatOut] = []

        for fmt in raw_formats:
            if not isinstance(fmt, dict):
                continue

            # yt-dlp sometimes returns entries without usable IDs
            format_id = fmt.get("format_id")
            if not format_id:
                continue

            # Skip non-video or special formats
            vcodec = fmt.get("vcodec")
            if vcodec in (None, "none"):
                continue

            # Optional: skip storyboard formats (youtube can include these)
            if fmt.get("format_note") == "storyboard":
                continue

            ext = fmt.get("ext") or "mp4"
            acodec = fmt.get("acodec")

            # filesize may be in different keys
            filesize = fmt.get("filesize") or fmt.get("filesize_approx")
            filesize_bytes = safe_int(filesize, default=None)

            formats_out.append(
                VideoFormatOut(
                    format_id=str(format_id),
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
