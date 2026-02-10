# video_downloader_api

FastAPI backend for multi-platform video downloading (YouTube, Instagram, Facebook, TikTok) with Celery worker support.

## Features

- Validate video links (domain allowlist + SSRF protection)
- Fetch video formats (quality + size if available) using `yt-dlp`
- Start downloads as background jobs (Celery)
- Status endpoint (polling)
- SSE endpoint for streaming progress (in-memory events)
- File serving endpoint for completed downloads

> Note: The current SSE implementation uses an **in-memory** event bus.
> If your worker is a separate process (Celery), you should replace it with Redis Pub/Sub for real production streaming.

---

## Project structure

- `main.py` - FastAPI app entrypoint
- `api/` - routes
- `services/` - business logic
- `downloader/` - yt-dlp wrapper
- `db/` - SQLAlchemy session + ORM models
- `repositories/` - DB operations
- `worker/` - Celery app + tasks
- `tasks/` - worker-side download execution logic
- `middleware/` - auth + SSRF safety helpers

---

## Environment variables

Create a `.env` file in project root (optional):

```env
DATABASE_URL=sqlite:///./video_downloader.db

REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Optional API key
# API_KEY=your-secret-key

# Optional: tighten CORS later
CORS_ORIGINS=*
