# video_downloader_api/downloader/ytdlp_downloader.py

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from functools import lru_cache
from logging import Logger
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import yt_dlp  # pip install yt-dlp

from video_downloader_api.core.config import get_settings
from video_downloader_api.core.logger import get_logger
from video_downloader_api.downloader.base import BaseDownloader

# Quality format_id from our API: "best" or numeric "144", "720", "1080" (optionally "720p")
_QUALITY_PATTERN = re.compile(r"^(?:best|\d+p?)$", re.IGNORECASE)


def _format_selector(format_id: str, *, merge: bool = True) -> str:
    """
    Build yt-dlp format string.
    With ffmpeg: merge best video + audio (YouTube/Instagram quality picks).
    Without ffmpeg: single-stream best (Instagram/TikTok usually ship one file).
    """
    format_id = (format_id or "").strip()
    if not format_id or format_id.lower() == "best":
        return "bestvideo+bestaudio/best" if merge else "best"

    match = re.match(r"^(\d+)p?$", format_id, re.IGNORECASE)
    if match:
        height = match.group(1)
        if merge:
            return f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"
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


# Sites that answer a non-browser TLS/HTTP fingerprint with "410 Gone" instead of
# the page. Impersonating a real browser is what gets past it.
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


def _needs_impersonation(url: str) -> bool:
    h = _host(url)
    return any(h == d or h.endswith("." + d) for d in _IMPERSONATE_DOMAINS)


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


def _url_prefers_login_cookies(url: str) -> bool:
    """Instagram / TikTok often need cookies for gated or sensitive posts."""
    return _is_instagram_url(url) or _is_tiktok_url(url)


def _cookie_file_pool(url: str) -> List[str]:
    """
    Cookie files for a specific URL/platform.
    YTDLP_COOKIES_FILE is treated as Instagram-only so IG session cookies
    are not sent to TikTok (they can trigger anti-bot failures).
    """
    settings = get_settings()
    seen: set[str] = set()
    out: List[str] = []

    def add(path: Optional[str]) -> None:
        p = (path or "").strip()
        if p and os.path.isfile(p) and p not in seen:
            seen.add(p)
            out.append(p)

    if _is_instagram_url(url):
        add(getattr(settings, "YTDLP_INSTAGRAM_COOKIES_FILE", None))
        files_csv = (settings.YTDLP_COOKIES_FILES or "").strip()
        if files_csv:
            for part in files_csv.split(","):
                add(part.strip())
        add(settings.YTDLP_COOKIES_FILE)
    elif _is_tiktok_url(url):
        add(getattr(settings, "YTDLP_TIKTOK_COOKIES_FILE", None))
    else:
        add(settings.YTDLP_COOKIES_FILE)
        files_csv = (settings.YTDLP_COOKIES_FILES or "").strip()
        if files_csv:
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
    Pornhub intermittently answers with a JS anti-bot page instead of the video page;
    yt-dlp reports that as a missing PhantomJS, since PhantomJS is what it would use
    to run the challenge script. The challenge is not sticky, so repeating the same
    request usually returns the real page.
    """
    return "phantomjs" in (message or "").lower()


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
    return shutil.which("deno")


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
    Without EJS, YouTube often falls back to 360p-only SABR formats.
    """
    opts: Dict[str, Any] = {
        "remote_components": ["ejs:github"],
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
    TikTok: request pacing; curl-cffi (optional dep) enables automatic impersonation.
    YouTube: EJS scripts + Deno for full resolution list.
    Adult sites: explicit browser impersonation to get past fingerprint blocking.
    """
    opts: Dict[str, Any] = {}
    if _is_tiktok_url(url):
        opts["sleep_interval_requests"] = 2
        opts["retries"] = 5
        opts["fragment_retries"] = 5
    if _is_youtube_url(url):
        opts.update(_youtube_ytdlp_opts())
    if _needs_impersonation(url):
        target = _impersonate_target()
        if target is not None:
            opts["impersonate"] = target
    return opts


def _friendly_extract_error(url: str, err: BaseException, *, dpapi_seen: bool) -> str:
    raw = str(err)
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
            info = ydl.extract_info(url, download=False)
            if info:
                ydl.process_ie_result(info, download=True)
                return
            ydl.download([url])

    def _run_with_cookie_fallback(
        self,
        url: str,
        base_opts: Dict[str, Any],
        runner: Callable[[Dict[str, Any]], Any],
        *,
        op_name: str,
    ) -> Any:
        """
        For Instagram/TikTok: try cookie files, then browser profiles, then no cookies.
        TikTok public videos often work without cookies, so when no cookie file is
        configured we try cookieless extraction before slow browser rotation.
        """
        last_err: Optional[BaseException] = None
        dpapi_seen = False

        base_work = dict(base_opts)
        base_work.update(_platform_ytdlp_opts(url))
        _apply_ffmpeg_options(base_work)
        if base_work.get("logger") is None:
            base_work["logger"] = _YtdlpQuietLogger(self.logger)

        def _attempt(opts: Dict[str, Any]) -> Any:
            # Both TikTok and the impersonated adult sites fail intermittently on
            # anti-bot challenges that clear on a repeat request.
            max_tries = 3 if (_is_tiktok_url(url) or _needs_impersonation(url)) else 1
            last: Optional[BaseException] = None
            for attempt in range(max_tries):
                try:
                    return runner(opts)
                except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError) as e:
                    last = e
                    if attempt + 1 < max_tries and (
                        _is_tiktok_transient_error(str(e))
                        or _is_bot_challenge_error(str(e))
                    ):
                        wait = 1 + attempt
                        self.logger.info(
                            "yt-dlp %s: transient anti-bot response, retry %s/%s in %ss for url=%s",
                            op_name,
                            attempt + 2,
                            max_tries,
                            wait,
                            url,
                        )
                        time.sleep(wait)
                        continue
                    raise
            if last:
                raise last
            raise RuntimeError("attempt failed without exception")

        def _try_without_cookies(*, final: bool) -> Any:
            nonlocal last_err
            opts = dict(base_work)
            opts.pop("cookiefile", None)
            opts.pop("cookiesfrombrowser", None)
            self.logger.info("yt-dlp %s: trying without cookies for url=%s", op_name, url)
            try:
                return _attempt(opts)
            except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError) as e:
                last_err = e
                if final:
                    friendly = _friendly_extract_error(url, e, dpapi_seen=dpapi_seen)
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

        if _url_prefers_login_cookies(url):
            cookie_files = _cookie_file_pool(url)

            # TikTok public videos work without cookies; IG cookies must not be sent.
            if _is_tiktok_url(url):
                try:
                    return _try_without_cookies(final=False)
                except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError):
                    pass
                for cf in cookie_files:
                    opts = dict(base_work)
                    _apply_cookie_options(opts, url, cookiefile_override=cf)
                    try:
                        self.logger.info(
                            "yt-dlp %s: trying cookie file %s for url=%s", op_name, cf, url
                        )
                        return _attempt(opts)
                    except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError) as e:
                        last_err = e
                        _raise_if_non_cookie_failure(e)
                        self.logger.warning(
                            "yt-dlp %s failed with cookie file %s for url=%s: %s",
                            op_name,
                            cf,
                            url,
                            e,
                        )
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

            for cf in cookie_files:
                opts = dict(base_work)
                _apply_cookie_options(opts, url, cookiefile_override=cf)
                try:
                    self.logger.info("yt-dlp %s: trying cookie file %s for url=%s", op_name, cf, url)
                    return _attempt(opts)
                except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError) as e:
                    last_err = e
                    _raise_if_non_cookie_failure(e)
                    self.logger.warning(
                        "yt-dlp %s failed with cookie file %s for url=%s: %s",
                        op_name,
                        cf,
                        url,
                        e,
                    )

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

        opts = dict(base_work)
        _apply_cookie_options(opts, url)
        try:
            # _attempt, not runner: this is the path every non-Instagram/TikTok URL
            # takes, so it needs the anti-bot retry too.
            return _attempt(opts)
        except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError) as e:
            err_msg = str(e)
            if _is_browser_cookie_database_error(err_msg) and os.name == "nt":
                for browser in ("edge", "firefox", "brave"):
                    opts2 = dict(base_work)
                    opts2.pop("cookiefile", None)
                    opts2.pop("cookiesfrombrowser", None)
                    opts2["cookiesfrombrowser"] = (browser,)
                    try:
                        self.logger.info(
                            "yt-dlp %s: Chrome cookie DB locked; retrying with browser=%s for url=%s",
                            op_name,
                            browser,
                            url,
                        )
                        return _attempt(opts2)
                    except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError):
                        continue
            last_err = e
            friendly = _friendly_extract_error(url, e, dpapi_seen=dpapi_seen)
            self.logger.warning("yt-dlp %s failed for url=%s: %s", op_name, url, friendly)
            raise ValueError(friendly) from e
        except Exception as e:
            self.logger.exception("yt-dlp %s failed for url=%s", op_name, url)
            raise RuntimeError(f"Failed to {op_name}: {e}") from e

    def extract_info(self, url: str) -> Dict[str, Any]:
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
        )

    def extract_playlist(self, url: str) -> Dict[str, Any]:
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

        format_selector = _format_selector(format_id, merge=_ffmpeg_available())
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
            base_opts["postprocessors"] = [
                {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"},
            ]

        try:
            self._run_with_cookie_fallback(
                url,
                base_opts,
                lambda o: self._download_impl(url, o),
                op_name="download",
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
