# video_downloader_api/db/session.py

from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from video_downloader_api.core.config import get_settings

settings = get_settings()

# SQLite needs this connect arg for multithreaded usage (FastAPI)
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine: Engine = create_engine(
    settings.DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency:
    Yields a DB session and always closes it after request finishes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
