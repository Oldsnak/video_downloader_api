# video_downloader_api/downloader/ytdlp_downloader.py

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from contextlib import contextmanager
from functools import lru_cache
from logging import Logger
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlparse

import yt_dlp  # pip install yt-dlp

from video_downloader_api.core.config import _project_root, get_settings
from video_downloader_api.core.logger import get_logger
from video_downloader_api.downloader.base import BaseDownloader

# Quality format_id from our API: "best" or numeric "144", "720", "1080" (optionally "720p")
_QUALITY_PATTERN = re.compile(r"^(?:best|\d+p?)$", re.IGNORECASE)


def _format_selector(
    format_id: str, *, merge: bool = True, youtube: bool = False
) -> str:
    """
    Build yt-dlp format string.
    With ffmpeg: merge best video + audio (YouTube/Instagram quality picks).
    Without ffmpeg: single-stream best (Instagram/TikTok usually ship one file).
    """
    format_id = (format_id or "").strip()
    if not format_id or format_id.lower() == "best":
        if youtube and merge:
            # HLS/progressive first. DASH avc1 itags 403 on googlevideo through
            # Webshare even when the watch page extract succeeded.
            return (
                "bv*[protocol^=m3u8]+ba/"
                "b[protocol^=m3u8]/"
                "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/"
                "bv*+ba/b"
            )
        return (
            "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/bv*+ba/b" if merge else "best"
        )

    match = re.match(r"^(\d+)p?$", format_id, re.IGNORECASE)
    if match:
        height = match.group(1)
        if merge:
            if youtube:
                return (
                    f"bv*[protocol^=m3u8][height<={height}]+ba/"
                    f"b[protocol^=m3u8][height<={height}]/"
                    f"bv*[vcodec^=avc1][height<={height}]+ba[acodec^=mp4a]/"
                    f"bv*[height<={height}]+ba/b[height<={height}]"
                )
            return (
                f"bv*[vcodec^=avc1][height<={height}]+ba[acodec^=mp4a]/"
                f"bv*[height<={height}]+ba/b[height<={height}]"
            )
        return f"best[height<={height}]"

    # Unknown (e.g., TikTok single-format id): use as-is; may be a single stream
    return format_id


def _is_quality_selector(format_id: str) -> bool:
    """True if format_id is our quality token (best or height) that needs merge."""
    if not format_id or not isinstance(format_id, str):
        return False
    return bool(_QUALITY_PATTERN.match(format_id.strip()))


def _host(url: str) -> str:
    raw = url.strip() if url else ""
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    h = (urlparse(raw).netloc or "").lower()
    if h.startswith("www."):
        h = h[4:]
    return h


def _is_instagram_url(url: str) -> bool:
    h = _host(url)
    return h == "instagram.com" or h.endswith(".instagram.com")


def _is_tiktok_url(url: str) -> bool:
    """tiktok.com and short links (vt., vm., etc.)."""
    h = _host(url)
    return h == "tiktok.com" or h.endswith(".tiktok.com")


def _is_youtube_url(url: str) -> bool:
    h = _host(url)
    return h in ("youtube.com", "youtu.be") or h.endswith(".youtube.com")


# Adult sites fingerprint-block non-browser TLS with 410/empty formats.
# YouTube must NOT be impersonated when using exported cookies — that combo
# makes yt-dlp report "The page needs to be reloaded".
# TikTok must NOT get an extra ImpersonateTarget("chrome"): curl_cffi then
# sends a Chrome 140–149 UA, and TikTok returns a bot page instead of the video.
# Instagram GraphQL often returns empty media under Chrome impersonate; the
# mobile web UA + phone cookies work better.
_IMPERSONATE_DOMAINS = (
    "pornhub.com",
    "pornhub.org",
    "pornhub.net",
    "xhamster.com",
    "xnxx.com",
    "xvideos.com",
    "desitales2.com",
    "darkero.com",
)

# TikTok currently blocks the Chrome 140–149 UA window that curl_cffi impersonate
# uses by default. Chrome 139 (or 130 / 150+) plus a www.tiktok.com Referer works.
_TIKTOK_WEB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.tiktok.com/",
}

_INSTAGRAM_WEB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36"
    ),
    "X-IG-App-ID": "936619743392459",
    "Referer": "https://www.instagram.com/",
}

# Netscape exports come from the owner's desktop browser. Pairing those
# cookies with the mobile UA above makes Instagram return empty media.
_INSTAGRAM_DESKTOP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    ),
    "X-IG-App-ID": "936619743392459",
    "Referer": "https://www.instagram.com/",
}


def _needs_impersonation(url: str) -> bool:
    h = _host(url)
    return any(h == d or h.endswith("." + d) for d in _IMPERSONATE_DOMAINS)


def _normalize_proxy_url(raw: str) -> Optional[str]:
    s = (raw or "").strip().strip('"').strip("'").rstrip("/")
    if not s:
        return None
    if "://" not in s:
        s = "http://" + s
    parsed = urlparse(s)
    if not parsed.hostname:
        return None
    return s


def _skip_country_codes() -> set[str]:
    raw = (getattr(get_settings(), "YTDLP_PROXY_SKIP_COUNTRIES", None) or "US").strip()
    return {p.strip().upper() for p in raw.replace(";", ",").split(",") if p.strip()}


_COUNTRY_CACHE: Dict[str, str] = {}
_TCP_OK: Dict[str, Tuple[float, bool]] = {}


def _fill_country_cache(hosts: List[str]) -> None:
    missing = [h for h in hosts if h and h not in _COUNTRY_CACHE]
    if not missing:
        return
    try:
        req = urllib.request.Request(
            "http://ip-api.com/batch?fields=query,status,countryCode",
            data=json.dumps(missing).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            rows = json.loads(resp.read().decode())
        if not isinstance(rows, list):
            rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            query = str(row.get("query") or "")
            if row.get("status") == "success":
                _COUNTRY_CACHE[query] = str(row.get("countryCode") or "").upper()
            elif query:
                _COUNTRY_CACHE[query] = ""
        for host in missing:
            _COUNTRY_CACHE.setdefault(host, "")
    except Exception as e:
        get_logger("YtDlpDownloader").warning("proxy country lookup failed: %s", e)
        for host in missing:
            _COUNTRY_CACHE.setdefault(host, "")


def _proxy_tcp_ok(proxy: str) -> bool:
    now = time.monotonic()
    cached = _TCP_OK.get(proxy)
    if cached and now - cached[0] < 60:
        return cached[1]
    parsed = urlparse(proxy)
    host = parsed.hostname
    port = parsed.port or 80
    ok = False
    if host:
        try:
            with socket.create_connection((host, port), timeout=2.5):
                ok = True
        except OSError:
            ok = False
    _TCP_OK[proxy] = (now, ok)
    return ok


@lru_cache(maxsize=1)
def _all_proxies() -> Tuple[str, ...]:
    """Every configured HTTP proxy, including countries skipped for YouTube."""
    settings = get_settings()
    seen: set[str] = set()
    out: List[str] = []

    def add(raw: Optional[str]) -> None:
        normalized = _normalize_proxy_url(raw or "")
        if normalized and normalized not in seen:
            seen.add(normalized)
            out.append(normalized)

    add(getattr(settings, "YTDLP_PROXY", None))
    csv = (getattr(settings, "YTDLP_PROXIES", None) or "").strip()
    if csv:
        for part in csv.split(","):
            add(part)

    user = (getattr(settings, "YTDLP_PROXY_USER", None) or "").strip()
    password = (getattr(settings, "YTDLP_PROXY_PASSWORD", None) or "").strip()
    endpoints = (getattr(settings, "YTDLP_PROXY_ENDPOINTS", None) or "").strip()
    if user and password and endpoints:
        for part in endpoints.split(","):
            hostport = part.strip()
            if not hostport:
                continue
            if "://" in hostport:
                parsed = urlparse(hostport)
                host = parsed.hostname or ""
                port = parsed.port
                if host and port:
                    add(f"http://{user}:{password}@{host}:{port}")
            else:
                add(f"http://{user}:{password}@{hostport}")

    return tuple(out)


@lru_cache(maxsize=1)
def _proxy_pool() -> Tuple[str, ...]:
    """HTTP proxies from env. Credentials stay in settings; never log the password."""
    out = list(_all_proxies())
    skip = _skip_country_codes()
    if skip and out:
        hosts = [urlparse(p).hostname or "" for p in out]
        _fill_country_cache(hosts)
        kept: List[str] = []
        dropped: List[str] = []
        for proxy in out:
            host = urlparse(proxy).hostname or ""
            country = _COUNTRY_CACHE.get(host, "")
            if country and country in skip:
                dropped.append(f"{host}({country})")
                continue
            kept.append(proxy)
        if dropped:
            get_logger("YtDlpDownloader").info(
                "skipping %s prox(ies) in blocked countries: %s",
                len(dropped),
                ", ".join(dropped),
            )
        if kept:
            out = kept
        else:
            get_logger("YtDlpDownloader").warning(
                "every proxy was in a blocked country; keeping the original pool"
            )
    return tuple(out)


def _session_cookie_proxy_chain() -> List[Optional[str]]:
    """
    One IP only when replaying the owner's logged-in session.

    Retrying the same session through GB, then ES, then JP within a few seconds
    is textbook session theft, and Instagram answers by killing the session
    server-side. Losing it logs the whole app out until cookies are re-exported,
    which costs far more than one failed extract, so cookie attempts never
    rotate. Proxy rotation still applies to cookieless attempts.
    """
    return [None]


_PROXY_RR_LOCK = threading.Lock()
_PROXY_RR_INDEX = 0
_PROXY_SUCCESS_LOCK = threading.Lock()
_PROXY_SUCCESS: Dict[str, str] = {}


def _proxy_affinity_key(url: str) -> str:
    """Stable id so /info and /start reuse the same Webshare exit IP."""
    raw = (url or "").strip()
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    if host in ("youtu.be", "www.youtu.be"):
        vid = path.strip("/").split("/", 1)[0]
        return f"yt:{vid}" if vid else raw
    if "youtube.com" in host:
        qs = parsed.query
        for part in qs.split("&"):
            if part.startswith("v=") and len(part) > 2:
                return f"yt:{part[2:]}"
        if "/shorts/" in path:
            vid = path.split("/shorts/", 1)[-1].split("/", 1)[0]
            return f"yt:{vid}" if vid else raw
        if "/embed/" in path:
            vid = path.split("/embed/", 1)[-1].split("/", 1)[0]
            return f"yt:{vid}" if vid else raw
    return f"{host}{path.rstrip('/')}".lower()


def _remember_working_proxy(url: str, proxy: Optional[str]) -> None:
    if not proxy or not url:
        return
    key = _proxy_affinity_key(url)
    if not key:
        return
    with _PROXY_SUCCESS_LOCK:
        _PROXY_SUCCESS[key] = proxy


def _forget_working_proxy(url: str, proxy: Optional[str]) -> None:
    if not proxy or not url:
        return
    key = _proxy_affinity_key(url)
    with _PROXY_SUCCESS_LOCK:
        if _PROXY_SUCCESS.get(key) == proxy:
            _PROXY_SUCCESS.pop(key, None)


# Cloudflare quick tunnels abort the origin at 120s. Extract must finish
# well under that, so we cap how many exit IPs /info will walk.
_MAX_EXTRACT_PROXY_ATTEMPTS = 4
_MAX_DOWNLOAD_PROXY_ATTEMPTS = 10


def _ordered_proxies(url: str = "", *, for_download: bool = False) -> List[Optional[str]]:
    """
    Prefer the exit IP that already unlocked this video.

    /info and /start used to round-robin independently, so YouTube metadata
    came from proxy A and the file download went through proxy B (instant 403).
    """
    pool = _proxy_pool()
    if not pool:
        return [None]
    preferred: Optional[str] = None
    key = _proxy_affinity_key(url) if url else ""
    if key:
        with _PROXY_SUCCESS_LOCK:
            candidate = _PROXY_SUCCESS.get(key)
        if candidate in pool or candidate in _all_proxies():
            preferred = candidate
    global _PROXY_RR_INDEX
    with _PROXY_RR_LOCK:
        start = _PROXY_RR_INDEX % len(pool)
        if preferred is None:
            _PROXY_RR_INDEX += 1
    rotated = list(pool[start:] + pool[:start])
    if preferred:
        chain = [preferred] + [p for p in rotated if p != preferred]
    else:
        chain = rotated
    limit = _MAX_DOWNLOAD_PROXY_ATTEMPTS if for_download else _MAX_EXTRACT_PROXY_ATTEMPTS
    return chain[:limit]


def _proxy_label(proxy: Optional[str]) -> str:
    if not proxy:
        return "direct"
    parsed = urlparse(proxy)
    host = parsed.hostname or "?"
    port = parsed.port
    return f"{host}:{port}" if port else host


def _short_err(message: str, limit: int = 120) -> str:
    text = " ".join((message or "").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _apply_proxy(opts: Dict[str, Any], proxy: Optional[str]) -> None:
    opts.pop("proxy", None)
    if proxy:
        opts["proxy"] = proxy


@lru_cache(maxsize=1)
def _impersonate_target() -> Optional[Any]:
    """
    Chrome impersonation target, or None when yt-dlp cannot load its curl_cffi
    backend.

    yt-dlp only accepts curl_cffi 0.5.10 and 0.10.x-0.15.x; on any other version it
    refuses to import the backend and every impersonate target becomes unavailable.
    Passing the option anyway aborts the extraction, so the caller must skip it.
    """
    try:
        import yt_dlp.networking._curlcffi  # noqa: F401
        from yt_dlp.networking.impersonate import ImpersonateTarget
    except Exception as e:
        get_logger("YtDlpDownloader").warning(
            "Browser impersonation unavailable (%s). Sites like Pornhub will fail "
            "with HTTP 410. Fix with: pip install 'curl-cffi>=0.10,<0.16'",
            e,
        )
        return None
    return ImpersonateTarget("chrome")


def _is_pornhub_url(url: str) -> bool:
    h = _host(url)
    return h in ("pornhub.com", "pornhub.org", "pornhub.net") or h.endswith(
        (".pornhub.com", ".pornhub.org", ".pornhub.net")
    )


def _resolve_cookie_path(path: Optional[str]) -> Optional[str]:
    p = (path or "").strip().strip('"').strip("'")
    if not p:
        return None
    if not os.path.isabs(p):
        p = os.path.join(_project_root(), p)
    p = os.path.normpath(p)
    return p if os.path.isfile(p) else None


def _url_prefers_login_cookies(url: str) -> bool:
    """Instagram / TikTok often need cookies for gated or sensitive posts."""
    return _is_instagram_url(url) or _is_tiktok_url(url)


@contextmanager
def _disposable_cookie_copy(path: str) -> Iterator[str]:
    """
    Hand yt-dlp a throwaway copy of a Netscape cookie file.

    When ``cookiefile`` is set, yt-dlp writes the whole jar back to that path as
    it closes. Instagram answers a request it dislikes with a logout
    ``Set-Cookie``, so yt-dlp would faithfully save a file with ``sessionid``
    deleted and silently log the server out for every future user.
    """
    fd, tmp = tempfile.mkstemp(prefix="ytdlp_cookies_", suffix=".txt")
    os.close(fd)
    try:
        shutil.copyfile(path, tmp)
        yield tmp
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _cookie_file_names(path: str) -> set[str]:
    """Cookie names in a Netscape file. Values are never read into memory."""
    names: set[str] = set()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("#HttpOnly_"):
                    line = line[len("#HttpOnly_") :]
                elif not line.strip() or line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 7 and parts[6].strip():
                    names.add(parts[5])
    except OSError:
        return names
    return names


def _has_login_session(path: str, url: str) -> bool:
    """True when the export actually carries a logged-in session cookie."""
    names = _cookie_file_names(path)
    if _is_instagram_url(url):
        return "sessionid" in names
    return bool(names)


def _cookie_file_pool(url: str) -> List[str]:
    """
    Cookie files for a specific URL/platform.

    Do not mix Instagram cookies into TikTok, or Instagram-only files into
    YouTube — each site needs its own logged-in Netscape export.
    """
    settings = get_settings()
    seen: set[str] = set()
    out: List[str] = []

    def add(path: Optional[str]) -> None:
        resolved = _resolve_cookie_path(path)
        if resolved and resolved not in seen:
            seen.add(resolved)
            out.append(resolved)

    if _is_instagram_url(url):
        add(getattr(settings, "YTDLP_INSTAGRAM_COOKIES_FILE", None))
        add(settings.YTDLP_COOKIES_FILE)
    elif _is_tiktok_url(url):
        add(getattr(settings, "YTDLP_TIKTOK_COOKIES_FILE", None))
    elif _is_youtube_url(url):
        add(getattr(settings, "YTDLP_YOUTUBE_COOKIES_FILE", None))
    elif _is_pornhub_url(url):
        add(getattr(settings, "YTDLP_PORNHUB_COOKIES_FILE", None))

    files_csv = (settings.YTDLP_COOKIES_FILES or "").strip()
    if files_csv and not _is_tiktok_url(url):
        for part in files_csv.split(","):
            add(part.strip())
    return out


def _is_tiktok_transient_error(message: str) -> bool:
    """Intermittent TikTok anti-bot / JS challenge failures worth retrying."""
    m = (message or "").lower()
    return (
        "unexpected response from webpage" in m
        or "unable to extract challenge" in m
        or "please wait" in m
    )


def _is_bot_challenge_error(message: str) -> bool:
    """
    Sites intermittently answer with a JS anti-bot / age-gate / login bounce.
    Repeating the request (especially with phone WebView cookies) often works.
    """
    m = (message or "").lower()
    return (
        "phantomjs" in m
        or "no video formats found" in m
        or "redirection detected" in m
        or "sign in to confirm" in m
        or "not a bot" in m
        or "empty media response" in m
        or "http error 403" in m
        or "http error 429" in m
        or "the page needs to be reloaded" in m
        or "ip address is blocked" in m
        or _is_tiktok_transient_error(message)
    )


def _is_proxy_rotatable_error(message: str) -> bool:
    """True when another exit IP is more likely to succeed than cookies or ffmpeg."""
    m = (message or "").lower()
    return (
        _is_bot_challenge_error(message)
        or "unable to extract" in m
        or "unable to download video data" in m
        or "timed out" in m
        or "timeout" in m
        or "connection reset" in m
        or "proxy error" in m
        or "tunnel connection" in m
        or "eof occurred" in m
        or "407" in m
        or "502" in m
        or "503" in m
    )


class _YtdlpQuietLogger:
    """
    Passed as yt-dlp ``logger`` so cookie extraction and report_error go through Python logging
    at DEBUG instead of stderr (avoids ERROR: lines for expected DPAPI / locked-DB failures).
    """

    def __init__(self, log: Logger) -> None:
        self._log = log

    def debug(self, message: str) -> None:
        self._log.debug("%s", message)

    def warning(
        self,
        message: str,
        *args: Any,
        once: bool = False,
        only_once: bool = False,
        **kwargs: Any,
    ) -> None:
        del once, only_once, args, kwargs
        self._log.debug("[yt-dlp] %s", message)

    def error(self, message: str, *args: Any, is_error: bool = True, **kwargs: Any) -> None:
        del is_error, args, kwargs
        self._log.debug("[yt-dlp] %s", message)


def _is_browser_cookie_database_error(message: str) -> bool:
    """True when yt-dlp could not read a browser cookie DB (e.g. Chrome locked on Windows)."""
    m = (message or "").lower()
    return "could not copy" in m and "cookie" in m


def _is_dpapi_cookie_error(message: str) -> bool:
    """True when Windows DPAPI cannot decrypt browser cookies (wrong user / service account)."""
    return "failed to decrypt with dpapi" in (message or "").lower()


def _is_cookie_auth_error(message: str) -> bool:
    """True when the extractor explicitly needs login cookies."""
    m = (message or "").lower()
    return "empty media response" in m or "login" in m and "cookie" in m


def _is_non_cookie_failure(message: str) -> bool:
    """True when failure is unrelated to cookies (do not drop cookiefile and retry)."""
    m = (message or "").lower()
    return (
        "ffmpeg is not installed" in m
        or "merging of multiple formats" in m
        or ("ffprobe" in m and "not installed" in m)
        or "application control policy" in m
    )


@lru_cache(maxsize=1)
def _deno_executable() -> Optional[str]:
    """Resolved deno path from settings or PATH (YouTube EJS challenge solving)."""
    settings = get_settings()
    configured = (getattr(settings, "YTDLP_DENO_PATH", None) or "").strip()
    if configured and os.path.isfile(configured):
        return configured
    found = shutil.which("deno")
    if found:
        return found
    # deno installs itself under $HOME and is only on PATH for shells that
    # sourced the profile. Without it YouTube's JS challenge cannot be solved,
    # so look in the install locations instead of trusting the parent process.
    for candidate in (
        os.path.expanduser("~/.deno/bin/deno"),
        "/usr/local/bin/deno",
        "/usr/bin/deno",
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


@lru_cache(maxsize=1)
def _ffmpeg_executable() -> Optional[str]:
    """Resolved ffmpeg path from settings or PATH, or None if not found."""
    settings = get_settings()
    configured = (getattr(settings, "FFMPEG_PATH", None) or "").strip()
    if configured and os.path.isfile(configured):
        return configured
    return shutil.which("ffmpeg")


@lru_cache(maxsize=1)
def _ffmpeg_available() -> bool:
    """True if ffmpeg exists and can execute (blocked policies count as unavailable)."""
    exe = _ffmpeg_executable()
    if not exe:
        return False
    try:
        subprocess.run(
            [exe, "-version"],
            capture_output=True,
            check=True,
            timeout=10,
        )
        return True
    except Exception:
        return False


def _apply_ffmpeg_options(opts: Dict[str, Any]) -> None:
    """Pass ffmpeg location to yt-dlp when configured or discovered."""
    exe = _ffmpeg_executable()
    if exe:
        opts["ffmpeg_location"] = os.path.dirname(os.path.abspath(exe))


def _cookie_setup_hint() -> str:
    return (
        "Set YTDLP_COOKIES_FILE in .env to a Netscape cookies.txt exported while logged into "
        "Instagram/TikTok (browser cookies often fail with DPAPI when the API runs as a service). "
        "See README.md."
    )


def _youtube_ytdlp_opts() -> Dict[str, Any]:
    """
    YouTube needs yt-dlp-ejs (pip) and preferably Deno for JS challenge solving.

    player_client is deliberately not pinned. Naming clients explicitly makes a
    broken one fatal: the "tv" client started answering "The page needs to be
    reloaded" and took every download with it, while yt-dlp's own default set
    skips a failing client and still returned formats up to 2160p. Leaving the
    choice to yt-dlp means an upstream breakage is repaired by upgrading it
    rather than by editing this list.
    """
    opts: Dict[str, Any] = {
        "remote_components": ["ejs:github"],
        "hls_prefer_native": True,
    }
    deno = _deno_executable()
    if deno:
        opts["js_runtimes"] = {"deno": {"path": deno}}
    else:
        opts["js_runtimes"] = {"deno": {}}
    return opts


def _platform_ytdlp_opts(url: str) -> Dict[str, Any]:
    """
    Extra yt-dlp options for platforms with anti-bot / JS challenges.
    TikTok: Chrome 139 UA + Referer (default impersonate UA is blocked).
    YouTube: EJS scripts + Deno; TV clients so media URLs are actually fetchable.
    Instagram: mobile web UA (Chrome impersonate returns empty media).
    Adult sites: explicit browser impersonation to get past fingerprint blocking.
    """
    opts: Dict[str, Any] = {}
    if _is_tiktok_url(url):
        opts["sleep_interval_requests"] = 2
        opts["retries"] = 5
        opts["fragment_retries"] = 5
        opts["http_headers"] = dict(_TIKTOK_WEB_HEADERS)
    if _is_instagram_url(url):
        opts["http_headers"] = dict(_INSTAGRAM_WEB_HEADERS)
    if _is_youtube_url(url):
        opts.update(_youtube_ytdlp_opts())
    if _needs_impersonation(url):
        target = _impersonate_target()
        if target is not None:
            opts["impersonate"] = target
    return opts


def _friendly_extract_error(
    url: str,
    err: BaseException,
    *,
    dpapi_seen: bool,
    session_expired: bool = False,
) -> str:
    raw = str(err)
    if session_expired and _is_instagram_url(url):
        # App users never sign in, so only the API owner can fix this.
        return (
            "This post is private or login-only, and the server's Instagram "
            "session has expired. Public posts still work."
        )
    if _is_dpapi_cookie_error(raw):
        return f"Browser cookies unavailable (DPAPI). {_cookie_setup_hint()}"
    if _is_cookie_auth_error(raw):
        prefix = "Browser cookies unavailable (DPAPI). " if dpapi_seen else ""
        return f"{raw} — {prefix}{_cookie_setup_hint()}"
    if _is_tiktok_url(url) and dpapi_seen and not _cookie_file_pool(url):
        return (
            f"{raw} — TikTok may need a newer yt-dlp + curl-cffi, or cookies for login-gated videos. "
            f"{_cookie_setup_hint()}"
        )
    if _needs_impersonation(url) and "410" in raw and _impersonate_target() is None:
        return (
            f"{raw} — this site blocks non-browser requests. Browser impersonation is "
            "unavailable; install a supported curl_cffi with: "
            "pip install 'curl-cffi>=0.10,<0.16'"
        )
    if _is_bot_challenge_error(raw):
        # The raw text tells the user to install PhantomJS, which is not the real
        # problem and not something an app user can act on.
        return "The site returned an anti-bot check instead of the video. Please try again."
    return raw


def _raise_if_non_cookie_failure(err: BaseException) -> None:
    """Re-raise immediately when cookies were fine but download failed for another reason."""
    msg = str(err)
    if _is_non_cookie_failure(msg):
        hint = (
            "ffmpeg is required to merge separate video/audio streams. "
            "Install ffmpeg, set FFMPEG_PATH in .env, or ensure Windows App Control "
            "is not blocking ffmpeg.exe."
        )
        raise ValueError(f"{msg} — {hint}") from err


def _browser_candidates_tiktok_instagram() -> List[str]:
    """
    Browsers to try for IG/TikTok when no cookie file worked.
    On Windows, Edge is tried before Chrome because Chrome's DB is often locked
    while Chrome is running (yt-dlp issue #7271).
    """
    settings = get_settings()
    configured = (settings.YTDLP_COOKIES_FROM_BROWSER or "").strip().lower()
    out: List[str] = []
    if configured:
        out.append(configured)
    if os.name == "nt":
        for b in ("edge", "firefox", "chrome", "brave", "chromium"):
            if b not in out:
                out.append(b)
    else:
        for b in ("chrome", "chromium", "firefox", "edge", "brave"):
            if b not in out:
                out.append(b)
    return out


def _apply_cookie_options(
    opts: Dict[str, Any],
    url: str,
    *,
    cookiefile_override: Optional[str] = None,
) -> None:
    """
    Mutates opts with cookiefile or cookiesfrombrowser.
    Never pass cookiesfrombrowser as a plain string (yt-dlp unpacks it per character).
    For TikTok/Instagram, cookie strategy is handled in _run_with_cookie_fallback instead.
    """
    settings = get_settings()
    opts.pop("cookiefile", None)
    opts.pop("cookiesfrombrowser", None)

    if cookiefile_override:
        opts["cookiefile"] = cookiefile_override
        return

    browser = (settings.YTDLP_COOKIES_FROM_BROWSER or "").strip().lower()
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
        return

    single = (settings.YTDLP_COOKIES_FILE or "").strip()
    if single and os.path.isfile(single):
        opts["cookiefile"] = single
        return

    if _url_prefers_login_cookies(url):
        # Actual browser rotation happens in _run_with_cookie_fallback (avoid Chrome-only default).
        opts["cookiesfrombrowser"] = ("edge",) if os.name == "nt" else ("chrome",)


class YtDlpDownloader(BaseDownloader):
    """
    Concrete downloader implementation using yt-dlp.

    Supports:
    - extract_info(url): fetch metadata without downloading
    - list_formats(info): return formats list from info
    - download(...): download a chosen format and report progress via callback
    """

    def __init__(self, logger: Optional[Logger] = None) -> None:
        self.logger: Logger = logger or get_logger(self.__class__.__name__)

    def _extract_info_impl(self, url: str, ydl_opts: Dict[str, Any]) -> Dict[str, Any]:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info or {}

    def _extract_playlist_impl(self, url: str, ydl_opts: Dict[str, Any]) -> Dict[str, Any]:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info or {}

    def _download_impl(self, url: str, ydl_opts: Dict[str, Any]) -> None:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

    def _run_with_cookie_fallback(
        self,
        url: str,
        base_opts: Dict[str, Any],
        runner: Callable[[Dict[str, Any]], Any],
        *,
        op_name: str,
        cookiefile: Optional[str] = None,
    ) -> Any:
        """
        For Instagram/TikTok: try cookie files, then browser profiles, then no cookies.
        TikTok public videos often work without cookies, so when no cookie file is
        configured we try cookieless extraction before slow browser rotation.
        """
        last_err: Optional[BaseException] = None
        dpapi_seen = False
        session_expired = False

        base_work = dict(base_opts)
        base_work.update(_platform_ytdlp_opts(url))
        _apply_ffmpeg_options(base_work)
        is_download = op_name == "download"
        # Keep /info inside Cloudflare's 120s origin timeout.
        base_work["socket_timeout"] = 20 if is_download else 12
        if base_work.get("logger") is None:
            base_work["logger"] = _YtdlpQuietLogger(self.logger)

        proxy_chain = _ordered_proxies(url, for_download=is_download)
        pool_size = len(_proxy_pool())
        if proxy_chain and proxy_chain[0] is not None:
            self.logger.info(
                "yt-dlp %s: using %s/%s HTTP proxy(ies), starting at %s for url=%s",
                op_name,
                len(proxy_chain),
                pool_size,
                _proxy_label(proxy_chain[0]),
                url,
            )

        def _attempt(opts: Dict[str, Any]) -> Any:
            # Rotate exit IPs on anti-bot / empty-format responses. A short inner
            # retry still helps TikTok and adult sites when the same proxy flakes.
            inner_tries = 1
            if is_download and (_is_tiktok_url(url) or _needs_impersonation(url)):
                inner_tries = 2
            chain = list(proxy_chain)
            if opts.get("cookiefile") and _url_prefers_login_cookies(url):
                chain = _session_cookie_proxy_chain()
            last: Optional[BaseException] = None
            for proxy_i, proxy in enumerate(chain):
                if proxy and not _proxy_tcp_ok(proxy):
                    self.logger.info(
                        "yt-dlp %s: skip unreachable %s for url=%s",
                        op_name,
                        _proxy_label(proxy),
                        url,
                    )
                    _forget_working_proxy(url, proxy)
                    last = yt_dlp.utils.DownloadError(
                        f"proxy unreachable: {_proxy_label(proxy)}"
                    )
                    continue
                work = dict(opts)
                _apply_proxy(work, proxy)
                for attempt in range(inner_tries):
                    try:
                        result = runner(work)
                        _remember_working_proxy(url, proxy)
                        return result
                    except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError) as e:
                        last = e
                        msg = str(e)
                        if _is_non_cookie_failure(msg):
                            raise
                        more_inner = attempt + 1 < inner_tries and _is_bot_challenge_error(msg)
                        if more_inner:
                            wait = 1 + attempt
                            self.logger.info(
                                "yt-dlp %s: transient anti-bot via %s, retry %s/%s in %ss for url=%s",
                                op_name,
                                _proxy_label(proxy),
                                attempt + 2,
                                inner_tries,
                                wait,
                                url,
                            )
                            time.sleep(wait)
                            continue
                        more_proxies = (
                            proxy_i + 1 < len(chain)
                            and _is_proxy_rotatable_error(msg)
                        )
                        if more_proxies:
                            _forget_working_proxy(url, proxy)
                            nxt = chain[proxy_i + 1]
                            self.logger.info(
                                "yt-dlp %s: %s failed via %s, rotating to %s for url=%s",
                                op_name,
                                _short_err(msg),
                                _proxy_label(proxy),
                                _proxy_label(nxt),
                                url,
                            )
                            break
                        raise
            if last:
                raise last
            raise RuntimeError("attempt failed without exception")

        def _try_without_cookies(*, final: bool) -> Any:
            nonlocal last_err, session_expired
            opts = dict(base_work)
            opts.pop("cookiefile", None)
            opts.pop("cookiesfrombrowser", None)
            self.logger.info("yt-dlp %s: trying without cookies for url=%s", op_name, url)
            try:
                return _attempt(opts)
            except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError) as e:
                last_err = e
                if final:
                    friendly = _friendly_extract_error(
                        url, e, dpapi_seen=dpapi_seen, session_expired=session_expired
                    )
                    self.logger.warning(
                        "yt-dlp %s failed (no cookies) for url=%s: %s", op_name, url, friendly
                    )
                    raise ValueError(friendly) from e
                self.logger.debug(
                    "yt-dlp %s failed without cookies for url=%s: %s", op_name, url, e
                )
                raise

        def _try_browser_cookies() -> Any:
            nonlocal last_err, dpapi_seen
            settings = get_settings()
            if not settings.YTDLP_TRY_BROWSER_COOKIES:
                self.logger.debug(
                    "yt-dlp %s: skipping cookiesfrombrowser (YTDLP_TRY_BROWSER_COOKIES=false) for url=%s",
                    op_name,
                    url,
                )
                raise last_err or yt_dlp.utils.DownloadError("browser cookies disabled")

            for browser in _browser_candidates_tiktok_instagram():
                if dpapi_seen:
                    break
                opts = dict(base_work)
                opts.pop("cookiefile", None)
                opts.pop("cookiesfrombrowser", None)
                opts["cookiesfrombrowser"] = (browser,)
                try:
                    self.logger.info(
                        "yt-dlp %s: trying cookiesfrombrowser=%s for url=%s",
                        op_name,
                        browser,
                        url,
                    )
                    return _attempt(opts)
                except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError) as e:
                    last_err = e
                    err_msg = str(e)
                    if _is_non_cookie_failure(err_msg):
                        _raise_if_non_cookie_failure(e)
                    if _is_dpapi_cookie_error(err_msg):
                        dpapi_seen = True
                        self.logger.warning(
                            "yt-dlp %s: browser cookies failed (DPAPI) for browser=%s — "
                            "API must run as the same Windows user as the browser, or use "
                            "YTDLP_COOKIES_FILE. Skipping remaining browsers.",
                            op_name,
                            browser,
                        )
                    else:
                        self.logger.debug(
                            "yt-dlp %s failed with browser=%s for url=%s: %s",
                            op_name,
                            browser,
                            url,
                            e,
                        )
            raise last_err or yt_dlp.utils.DownloadError("no browser cookies worked")

        def _try_client_cookies() -> Any:
            if not cookiefile or not os.path.isfile(cookiefile):
                raise yt_dlp.utils.DownloadError("no client cookiefile")
            opts = dict(base_work)
            _apply_cookie_options(opts, url, cookiefile_override=cookiefile)
            self.logger.info(
                "yt-dlp %s: trying phone WebView cookies for url=%s", op_name, url
            )
            return _attempt(opts)

        # Owner-supplied Netscape cookies on the API host the session so app
        # users never log in. Phone WebView cookies are optional extras.
        youtube = _is_youtube_url(url)
        instagram = _is_instagram_url(url)
        if cookiefile and youtube:
            self.logger.info(
                "yt-dlp %s: skipping phone YouTube cookies (IP-bound) for url=%s",
                op_name,
                url,
            )

        cookie_files = _cookie_file_pool(url)

        def _try_server_cookie_files() -> Any:
            nonlocal last_err, session_expired
            if not cookie_files:
                raise yt_dlp.utils.DownloadError("no server cookie file")
            for cf in cookie_files:
                if youtube:
                    continue
                if not _has_login_session(cf, url):
                    session_expired = True
                    self.logger.error(
                        "yt-dlp %s: cookie file %s has no login session cookie; "
                        "re-export it while signed in, otherwise gated posts fail",
                        op_name,
                        cf,
                    )
                    continue
                with _disposable_cookie_copy(cf) as safe_cf:
                    opts = dict(base_work)
                    _apply_cookie_options(opts, url, cookiefile_override=safe_cf)
                    if instagram:
                        opts["http_headers"] = dict(_INSTAGRAM_DESKTOP_HEADERS)
                    try:
                        self.logger.info(
                            "yt-dlp %s: trying cookie file %s for url=%s", op_name, cf, url
                        )
                        return _attempt(opts)
                    except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError) as e:
                        last_err = e
                        _raise_if_non_cookie_failure(e)
                        if _is_cookie_auth_error(str(e)):
                            session_expired = True
                        self.logger.warning(
                            "yt-dlp %s failed with cookie file %s for url=%s: %s",
                            op_name,
                            cf,
                            url,
                            e,
                        )
            raise yt_dlp.utils.DownloadError("no server cookie file worked")

        # Instagram / adult: use the API owner's cookies first so end users
        # do not sign in inside the app.
        if instagram or _needs_impersonation(url):
            try:
                return _try_server_cookie_files()
            except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError):
                pass

        if _is_tiktok_url(url) or youtube or instagram or bool(_proxy_pool()):
            try:
                return _try_without_cookies(final=False)
            except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError):
                pass

        if cookiefile and os.path.isfile(cookiefile) and not youtube:
            try:
                return _try_client_cookies()
            except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError) as e:
                last_err = e
                self.logger.info(
                    "yt-dlp %s: phone cookies did not unlock url=%s; trying other strategies",
                    op_name,
                    url,
                )

        if not instagram and not _needs_impersonation(url):
            try:
                return _try_server_cookie_files()
            except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError):
                pass

        if last_err is not None and (youtube or instagram):
            friendly = _friendly_extract_error(
                url, last_err, dpapi_seen=dpapi_seen, session_expired=session_expired
            )
            raise ValueError(friendly) from last_err

        if not youtube:
            try:
                return _try_browser_cookies()
            except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError):
                pass

        try:
            return _try_without_cookies(final=True)
        except ValueError:
            raise
        except Exception as e:
            self.logger.exception("yt-dlp %s failed for url=%s", op_name, url)
            raise RuntimeError(f"Failed to {op_name}: {e}") from e

    def extract_info(self, url: str, cookiefile: Optional[str] = None) -> Dict[str, Any]:
        """
        Calls yt-dlp with download=False to retrieve metadata.
        """
        base_opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
        }

        return self._run_with_cookie_fallback(
            url,
            base_opts,
            lambda o: self._extract_info_impl(url, o),
            op_name="extract_info",
            cookiefile=cookiefile,
        )

    def extract_playlist(self, url: str, cookiefile: Optional[str] = None) -> Dict[str, Any]:
        """
        Extract high-level playlist information (entries) without downloading.
        """
        base_opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": False,
            "extract_flat": True,
            "skip_download": True,
        }

        return self._run_with_cookie_fallback(
            url,
            base_opts,
            lambda o: self._extract_playlist_impl(url, o),
            op_name="extract_playlist",
            cookiefile=cookiefile,
        )

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
        cookiefile: Optional[str] = None,
    ) -> str:
        """
        Downloads a specific format using yt-dlp. For quality-based ids (e.g. "720",
        "best") uses merged bestvideo+bestaudio so output has both video and audio.
        """
        out_dir = os.path.dirname(os.path.abspath(output_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        resolved_path: List[str] = []

        def _hook(d: Dict[str, Any]) -> None:
            if d.get("status") == "finished":
                finished = d.get("filename")
                if isinstance(finished, str) and finished.strip():
                    resolved_path.append(finished)
            try:
                progress_cb(d)
            except Exception:
                self.logger.exception("Progress callback failed (job may still continue).")

        format_selector = _format_selector(
            format_id, merge=_ffmpeg_available(), youtube=_is_youtube_url(url)
        )
        use_merge = _is_quality_selector(format_id) and _ffmpeg_available()

        base_opts: Dict[str, Any] = {
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
            # Remux only. FFmpegVideoConvertor re-encodes VP9→H.264 and can
            # stall or fail a YouTube job for minutes on a small Codespace CPU.
            base_opts["merge_output_format"] = "mp4"

        try:
            self._run_with_cookie_fallback(
                url,
                base_opts,
                lambda o: self._download_impl(url, o),
                op_name="download",
                cookiefile=cookiefile,
            )
            if resolved_path:
                return resolved_path[-1]
            if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
                return output_path
            alt = f"{output_path}.mp4"
            if os.path.isfile(alt) and os.path.getsize(alt) > 0:
                return alt
            return output_path
        except ValueError as e:
            raise RuntimeError(f"Failed to download video: {e}") from e
        except RuntimeError:
            raise
