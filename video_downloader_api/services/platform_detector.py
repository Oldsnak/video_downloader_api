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
        # The host is deliberately left as-is, including any "www." prefix: this URL
        # is handed to yt-dlp, and some sites (Pornhub) serve a JS bot-challenge page
        # on the apex domain while the www host returns the real page. Platform
        # detection and the domain allowlist strip "www." on their own, so keeping it
        # here does not affect matching.
        netloc = parsed.netloc.lower()

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

    # Adult sites use many country/language subdomains (e.g. rt.pornhub.com,
    # xh.video mirrors), so these are matched on the registrable domain.
    _ADULT_DOMAINS = {
        "pornhub.com": Platform.PORNHUB,
        "xhamster.com": Platform.XHAMSTER,
        "xnxx.com": Platform.XNXX,
        "xvideos.com": Platform.XVIDEOS,
        "desitales2.com": Platform.DESITALES,
        "darkero.com": Platform.DARKERO,
    }

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

        for domain, platform in self._ADULT_DOMAINS.items():
            if host == domain or host.endswith("." + domain):
                return platform.value

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
