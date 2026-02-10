# video_downloader_api/db/models.py

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class DownloadJob(Base):
    """
    Database model for download jobs.
    Stores job state, progress, and final file details.
    """

    __tablename__ = "download_jobs"

    # UUID string primary key
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    format_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    quality: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    downloaded_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    speed_bps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    eta_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    file_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    public_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
