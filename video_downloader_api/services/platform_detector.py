# video_downloader_api/services/platform_detector.py

from __future__ import annotations

from typing import List
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from video_downloader_api.enums import Platform


class PlatformDetector:
    """
    Detects platform and normalizes URLs.
    """

    def normalize_url(self, url: str) -> str:
        """
        Normalize incoming URL:
        - Ensure scheme (https)
        - Lowercase host
        - Remove common tracking query params
        - Remove fragments
        """
        raw = url.strip()

        if not raw.startswith(("http://", "https://")):
            raw = "https://" + raw

        parsed = urlparse(raw)
        netloc = parsed.netloc.lower()

        # Strip leading www.
        if netloc.startswith("www."):
            netloc = netloc[4:]

        # Remove tracking params
        tracking_keys = {
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
            "fbclid",
            "gclid",
            "igshid",
        }

        query_params = []
        for k, v in parse_qsl(parsed.query, keep_blank_values=True):
            if k.lower() not in tracking_keys:
                query_params.append((k, v))

        new_query = urlencode(query_params)

        normalized = urlunparse(
            (
                parsed.scheme or "https",
                netloc,
                parsed.path,
                parsed.params,
                new_query,
                "",  # drop fragment
            )
        )
        return normalized

    def detect_platform(self, url: str) -> str:
        """
        Returns platform string based on hostname.
        """
        parsed = urlparse(url if url.startswith(("http://", "https://")) else "https://" + url)
        host = (parsed.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]

        if host in ("youtube.com", "youtu.be") or host.endswith(".youtube.com"):
            return Platform.YOUTUBE.value
        if host == "instagram.com" or host.endswith(".instagram.com"):
            return Platform.INSTAGRAM.value
        if host in ("facebook.com", "fb.watch") or host.endswith(".facebook.com"):
            return Platform.FACEBOOK.value
        if host == "tiktok.com" or host.endswith(".tiktok.com"):
            return Platform.TIKTOK.value

        return Platform.UNKNOWN.value

    def is_allowed_domain(self, url: str, allowed_domains: List[str]) -> bool:
        """
        Checks hostname matches allowed domains (exact or subdomain).
        """
        parsed = urlparse(url if url.startswith(("http://", "https://")) else "https://" + url)
        host = (parsed.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]

        allowed = [d.lower().strip() for d in allowed_domains]

        # exact match or subdomain match
        for d in allowed:
            if host == d or host.endswith("." + d):
                return True
        return False
