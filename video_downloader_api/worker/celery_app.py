from __future__ import annotations

from celery import Celery
from video_downloader_api.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "video_downloader_api",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.task_default_queue = "downloads"
celery_app.conf.task_routes = {
    "worker.tasks.run_download": {"queue": "downloads"},
}

# ✅ simplest: directly import tasks so they register
import video_downloader_api.worker.tasks  # noqa: F401
