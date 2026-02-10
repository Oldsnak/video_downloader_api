# video_downloader_api/core/logger.py

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

# Central logging format used across the whole project
LOG_FORMAT: str = (
    "%(asctime)s | %(levelname)s | %(name)s | %(filename)s:%(lineno)d | %(message)s"
)

# Default log level (can be overridden via env var: LOG_LEVEL)
DEFAULT_LEVEL: str = "INFO"


class _SingleLineFormatter(logging.Formatter):
    """Ensures logs remain single-line (better for parsing and production logs)."""

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        return msg.replace("\n", "\\n").replace("\r", "\\r")


def _resolve_level(level: Optional[str]) -> int:
    """Convert level string -> logging level int. Fallback to DEFAULT_LEVEL."""
    level_str = (level or DEFAULT_LEVEL).strip().upper()
    return getattr(logging, level_str, logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """
    Returns a configured logger (project-wide standard).

    - Reads LOG_LEVEL from environment (fallback DEFAULT_LEVEL)
    - Logs to stdout
    - Avoids duplicate handlers on repeated imports
    """
    logger = logging.getLogger(name)

    # Set base level (logger + handler)
    env_level = os.getenv("LOG_LEVEL", DEFAULT_LEVEL)
    level = _resolve_level(env_level)
    logger.setLevel(level)

    # Prevent duplicate logs if uvicorn reloads/imports multiple times
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        handler.setFormatter(_SingleLineFormatter(LOG_FORMAT))
        logger.addHandler(handler)

    # Prevent propagating to root (avoids double logging with uvicorn)
    logger.propagate = False
    return logger
