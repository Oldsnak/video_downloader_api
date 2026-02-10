# video_downloader_api/utils/rate_limiter.py

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request, status


class SimpleRateLimiter:
    """
    A simple in-memory rate limiter.

    NOTE:
    - Works only for a single FastAPI instance (no multi-server scaling).
    - For production, replace with Redis-based limiter.

    How it works:
    - Keeps timestamps of recent hits per key (IP or API key).
    - If hits in the last window exceed limit -> HTTP 429.
    """

    def __init__(self, max_requests: int = 30, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def _cleanup(self, key: str, now: float) -> None:
        q = self._hits[key]
        boundary = now - self.window_seconds
        while q and q[0] < boundary:
            q.popleft()

    def allow(self, key: str) -> bool:
        now = time.time()
        self._cleanup(key, now)

        q = self._hits[key]
        if len(q) >= self.max_requests:
            return False

        q.append(now)
        return True


# Global limiter instance (tune as needed)
rate_limiter = SimpleRateLimiter(max_requests=40, window_seconds=60)


def rate_limit_dependency(request: Request, key_override: Optional[str] = None) -> None:
    """
    FastAPI dependency function.

    Use as:
        Depends(rate_limit_dependency)

    Key strategy:
    - If key_override given -> use it
    - Else use client IP
    """
    key = key_override
    if not key:
        key = request.client.host if request.client else "unknown"

    if not rate_limiter.allow(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
        )
