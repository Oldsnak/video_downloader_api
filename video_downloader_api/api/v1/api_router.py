# video_downloader_api/api/v1/api_router.py

from __future__ import annotations

from fastapi import APIRouter

from video_downloader_api.api.v1.routes.download import router as download_router
from video_downloader_api.api.v1.routes.download_status import router as download_status_router
from video_downloader_api.api.v1.routes.stream import router as stream_router
from video_downloader_api.api.v1.routes.files import router as files_router
from video_downloader_api.api.v1.routes.health import router as health_router

api_router = APIRouter()

api_router.include_router(health_router, tags=["health"])
api_router.include_router(download_router, tags=["download"])
api_router.include_router(download_status_router, tags=["download"])
api_router.include_router(stream_router, tags=["download"])
api_router.include_router(files_router, tags=["files"])
