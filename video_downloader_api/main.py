# video_downloader_api/main.py

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from video_downloader_api.api.v1.api_router import api_router
from video_downloader_api.core.config import get_settings
from video_downloader_api.core.logger import get_logger

from sqlalchemy import text

from video_downloader_api.db.models import Base
from video_downloader_api.db.session import engine


logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan startup/shutdown handlers.
    Ensures download directory + DB tables exist.
    """
    settings = get_settings()

    # ✅ Ensure downloads folder
    try:
        os.makedirs(settings.DOWNLOAD_DIR, exist_ok=True)
        logger.info("✅ Download dir ensured: %s", settings.DOWNLOAD_DIR)
    except Exception as e:
        logger.exception("❌ Failed to create download dir: %s", e)

    # ✅ Ensure DB tables
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("✅ DB tables ensured.")
    except Exception as e:
        logger.exception("❌ Failed to create DB tables: %s", e)

    # ✅ Migration: add 'title' column to download_jobs if missing (existing DBs)
    try:
        with engine.connect() as conn:
            if "sqlite" in (settings.DATABASE_URL or "").lower():
                r = conn.execute(text("PRAGMA table_info(download_jobs)"))
                columns = [row[1] for row in r]
                if "title" not in columns:
                    conn.execute(text("ALTER TABLE download_jobs ADD COLUMN title VARCHAR(512)"))
                    conn.commit()
                    logger.info("✅ Added 'title' column to download_jobs.")
    except Exception as e:
        logger.exception("⚠️ Migration (title column) skipped or failed: %s", e)

    yield

    logger.info("👋 Shutting down...")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS if settings.CORS_ORIGINS else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    return app


app = create_app()
