# video_downloader_api/middleware/security.py

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import HTTPException, status


def block_private_ips(hostname: str) -> None:
    """
    Resolve hostname and block private/local/link-local/reserved IP ranges.
    Protects against SSRF like:
      - http://127.0.0.1:8000
      - http://localhost
      - http://169.254.169.254 (cloud metadata)
      - http://10.x.x.x
    """
    try:
        # getaddrinfo returns multiple addresses (IPv4/IPv6)
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to resolve hostname.",
        )

    for info in infos:
        ip_str = info[4][0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_reserved
            or ip_obj.is_multicast
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Blocked hostname/IP (SSRF protection).",
            )


def validate_url_safe(url: str) -> None:
    """
    Validate URL safety rules:
    - only http/https
    - must have hostname
    - block private IPs / localhost
    """
    raw = url.strip()
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw

    parsed = urlparse(raw)

    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only http/https URLs are allowed.",
        )

    if not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid URL (missing hostname).",
        )

    host = parsed.hostname
    if not host:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid URL (unable to parse hostname).",
        )

    if host.lower() in ("localhost",):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Blocked hostname (SSRF protection).",
        )

    block_private_ips(host)
