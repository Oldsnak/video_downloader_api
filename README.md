# video_downloader_api

FastAPI backend for multi-platform video downloading (YouTube, Instagram, Facebook, TikTok) with Celery worker support. Suitable for **SaaS**: files are streamed to the client (e.g. Flutter) and optionally deleted from the server after streaming.

## Features

- Validate video links (domain allowlist + SSRF protection)
- Fetch video formats: **one option per quality** (no duplicate 720p entries); video+audio merged for YouTube/Instagram
- Start downloads as background jobs (Celery); **multiple jobs run in parallel**
- Status endpoint (polling)
- SSE endpoint for streaming progress (in-memory events)
- **Stream completed file to client** (Flutter downloads from `file_url` and saves to device); optional server-side delete after stream

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

# Concurrent downloads (Celery worker concurrency)
MAX_CONCURRENT_DOWNLOADS=3

# SaaS: delete file from server after streaming to client (default: true)
DELETE_FILE_AFTER_STREAM=true

# Optional API key
# API_KEY=your-secret-key

# Optional: tighten CORS later
CORS_ORIGINS=*
```

## Running the worker (concurrent downloads)

Start the Celery worker so multiple download requests can run at once:

```bash
celery -A video_downloader_api.worker.celery_app worker --loglevel=info -Q downloads
```

Concurrency is read from `MAX_CONCURRENT_DOWNLOADS` (default 3). Override with `--concurrency=N` if needed.
