# video_downloader_api/core/config.py

from __future__ import annotations

import os
from functools import lru_cache
from typing import List, Optional, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _project_root() -> str:
    """Directory that contains the video_downloader_api package. Same for API and worker."""
    _here = os.path.dirname(os.path.abspath(__file__))  # core/
    _pkg = os.path.dirname(_here)  # video_downloader_api/
    return os.path.dirname(_pkg)  # project root


def _parse_list(v: Any) -> List[str]:
    """
    Accepts:
      - Python list (already parsed)
      - JSON string list: '["a","b"]'
      - CSV string: "a,b,c"
      - '*' as wildcard (for CORS)
    Returns a clean list of strings.
    """
    if v is None:
        return []

    # already list
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]

    # string input
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return []

        # allow "*" for cors shorthand
        if s == "*":
            return ["*"]

        # try JSON list first
        if s.startswith("[") and s.endswith("]"):
            import json

            try:
                data = json.loads(s)
                if isinstance(data, list):
                    return [str(x).strip() for x in data if str(x).strip()]
            except Exception:
                # fall back to csv below
                pass

        # CSV fallback
        parts = [p.strip() for p in s.split(",")]
        return [p for p in parts if p]

    # unknown type -> best effort
    return [str(v).strip()] if str(v).strip() else []


class Settings(BaseSettings):
    """
    Central app configuration loaded from environment variables.
    Supports:
    - .env file
    - OS environment variables
    """

    # -------------------------
    # App basics
    # -------------------------
    APP_NAME: str = "video_downloader_api"
    API_V1_PREFIX: str = "/api/v1"

    # -------------------------
    # Allowed platforms/domains
    # -------------------------
    # .env accepted formats:
    # ALLOWED_DOMAINS=youtube.com,youtu.be,instagram.com
    # ALLOWED_DOMAINS=["youtube.com","youtu.be","instagram.com"]
    ALLOWED_DOMAINS: List[str] = Field(
        default_factory=lambda: [
            "youtube.com",
            "youtu.be",
            "instagram.com",
            "facebook.com",
            "fb.watch",
            "tiktok.com",
        ]
    )

    # -------------------------
    # Downloads
    # -------------------------
    DOWNLOAD_DIR: str = "downloads"

    @field_validator("DOWNLOAD_DIR", mode="after")
    @classmethod
    def _resolve_download_dir_absolute(cls, v: str) -> str:
        """Resolve to same absolute path for API and worker (fixes 404 when worker CWD differs)."""
        if not v or not isinstance(v, str):
            return os.path.join(_project_root(), "downloads")
        v = v.strip()
        if not os.path.isabs(v):
            v = os.path.join(_project_root(), v)
        return os.path.abspath(v)

    MAX_CONCURRENT_DOWNLOADS: int = 3
    MAX_FILE_SIZE_MB: int = 2000
    # SaaS: delete file after it is streamed to client (no long-term storage)
    DELETE_FILE_AFTER_STREAM: bool = True

    # -------------------------
    # Redis + DB
    # -------------------------
    REDIS_URL: str = "redis://localhost:6379/0"
    DATABASE_URL: str = "sqlite:///./video_downloader.db"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # -------------------------
    # Security
    # -------------------------
    API_KEY: Optional[str] = None

    # CORS
    # .env accepted formats:
    # CORS_ORIGINS=*
    # CORS_ORIGINS=http://localhost:3000,http://localhost:5173
    # CORS_ORIGINS=["http://localhost:3000","http://localhost:5173"]
    CORS_ORIGINS: List[str] = Field(default_factory=lambda: ["*"])

    # -------------------------
    # Pydantic Settings config
    # -------------------------
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # -------------------------
    # Validators (env parsing)
    # -------------------------
    @field_validator("ALLOWED_DOMAINS", mode="before")
    @classmethod
    def _validate_allowed_domains(cls, v: Any) -> List[str]:
        out = _parse_list(v)
        # normalize domains (lower + strip + remove "www.")
        cleaned: List[str] = []
        for d in out:
            x = d.lower().strip()
            if x.startswith("www."):
                x = x[4:]
            if x and x not in cleaned:
                cleaned.append(x)
        return cleaned

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _validate_cors_origins(cls, v: Any) -> List[str]:
        out = _parse_list(v)
        if not out:
            return ["*"]
        return out

    def is_domain_allowed(self, domain: str) -> bool:
        """
        Helper method: checks if a domain is allowed.
        """
        domain = domain.lower().strip()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain in self.ALLOWED_DOMAINS


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Cached singleton settings object.
    """
    return Settings()
