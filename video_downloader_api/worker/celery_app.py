from __future__ import annotations

from celery import Celery
from video_downloader_api.core.config import get_settings

settings = get_settings()

_eager = getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)

celery_app = Celery(
    "video_downloader_api",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.task_default_queue = "downloads"
celery_app.conf.task_routes = {
    "worker.tasks.run_download": {"queue": "downloads"},
}

# Run multiple download tasks in parallel (override with: celery -A ... worker --concurrency=N)
celery_app.conf.worker_concurrency = settings.MAX_CONCURRENT_DOWNLOADS

# Local dev without Redis: tasks execute immediately inside the API process.
celery_app.conf.task_always_eager = _eager
celery_app.conf.task_eager_propagates = _eager

# ✅ simplest: directly import tasks so they register
import video_downloader_api.worker.tasks  # noqa: F401
