"""
Report whether the API owner's Instagram cookies still carry a live session.

App users never sign in, so gated posts work only while this export is valid.
Run after replacing cookies/instagram.txt:

    python tools/check_instagram_session.py cookies/instagram.txt

Cookie values are never printed.
"""

from __future__ import annotations

import http.cookiejar
import sys
import urllib.error
import urllib.request

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
)


def main(path: str) -> int:
    jar = http.cookiejar.MozillaCookieJar()
    try:
        jar.load(path, ignore_discard=True, ignore_expires=True)
    except OSError as e:
        print(f"cannot read {path}: {e}")
        return 2

    names = {c.name for c in jar if (c.value or "").strip()}
    print(f"cookies_loaded {len(names)}")
    if "sessionid" not in names:
        print("result FAIL: no sessionid — export again while signed in to Instagram")
        return 1

    csrf = next((c.value for c in jar if c.name == "csrftoken"), "")
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(
        "https://www.instagram.com/api/v1/users/web_profile_info/?username=instagram",
        headers={
            "User-Agent": _UA,
            "Accept": "*/*",
            "X-IG-App-ID": "936619743392459",
            "X-CSRFToken": csrf,
            "Referer": "https://www.instagram.com/",
        },
    )
    try:
        with opener.open(req, timeout=30) as r:
            status, body = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # network down, DNS, proxy
        print(f"result UNKNOWN: request failed ({type(e).__name__})")
        return 3

    if status == 200 and '"user"' in body:
        print("result OK: session is live, gated posts will work")
        return 0
    if status == 429:
        print("result UNKNOWN: Instagram rate-limited this IP, retry in a few minutes")
        return 3
    if "not-logged-in" in body or status in (401, 403):
        print("result FAIL: session rejected — export again while signed in to Instagram")
        return 1
    print(f"result UNKNOWN: unexpected status {status}")
    return 3


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "cookies/instagram.txt"
    raise SystemExit(main(target))
