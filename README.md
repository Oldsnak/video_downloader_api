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

# SaaS: delete file from server once the client has received it in full (default: true).
# A client that disconnects mid-transfer keeps the file on the server so it can
# resume via a Range request instead of losing the download.
DELETE_FILE_AFTER_STREAM=true

# Optional API key
# API_KEY=your-secret-key

# Optional: tighten CORS later
CORS_ORIGINS=*

# Instagram / TikTok: many posts need a logged-in session (sensitive content, empty media, etc.)
# Option A — export Netscape cookies.txt from browser (recommended on servers without Chrome profile)
# YTDLP_COOKIES_FILE=/absolute/path/to/cookies.txt
# Option B — try several cookie files in order (comma-separated)
# YTDLP_COOKIES_FILES=/path/a.txt,/path/b.txt
# Option C — read cookies from a local browser profile (Windows dev machine with TikTok/IG logged in)
# YTDLP_COOKIES_FROM_BROWSER=chrome
# If unset, TikTok and Instagram URLs try cookie files, then several browsers in order.
# On Windows, Edge is tried before Chrome because Chrome’s cookie DB is often locked while Chrome is running
# (see https://github.com/yt-dlp/yt-dlp/issues/7271 ). Prefer YTDLP_COOKIES_FILE if browser cookies keep failing.
#
# Browser cookies must run under the same Windows user as the browser (DPAPI); otherwise Edge fails with
# “Failed to decrypt with DPAPI” ( https://github.com/yt-dlp/yt-dlp/issues/10927 ). Services / different
# accounts should use YTDLP_COOKIES_FILE instead.
#
# Skip rotating through browsers after cookie files (less log noise if you only use cookies.txt):
# YTDLP_TRY_BROWSER_COOKIES=false

# YouTube: full quality list (720p, 1080p, etc.) requires yt-dlp-ejs (in requirements.txt).
# Install Deno for best results (winget install DenoLand.Deno) or set an explicit path:
# YTDLP_DENO_PATH=C:\Users\you\.deno\bin\deno.exe
#
# ffmpeg merges separate YouTube video/audio streams — set FFMPEG_PATH if not on PATH:
# FFMPEG_PATH=C:\ProgramData\chocolatey\bin\ffmpeg.exe
```

## Running the worker (concurrent downloads)

Celery needs **Redis** on `localhost:6379`. On Windows, [Memurai Developer](https://www.memurai.com/) is the usual choice.

### Option A — start Redis (Memurai)

```powershell
# From video_downloader_api/
.\scripts\start-redis.ps1
```

If that fails, open **PowerShell as Administrator** and run `Start-Service Memurai`.

Memurai Developer **auto-stops every 10 days**; re-run the script or restart the service when you see `Error 10061 connecting to localhost:6379`.

### Option B — no Redis (local dev only)

Add to `.env`:

```env
CELERY_TASK_ALWAYS_EAGER=true
```

Downloads run inside the FastAPI process. You do **not** need a Celery worker, but only one download runs at a time.

### Start the Celery worker (Option A only)

```bash
celery -A video_downloader_api.worker.celery_app worker --loglevel=info -Q downloads -P solo
```

On Windows use `-P solo`. Concurrency is read from `MAX_CONCURRENT_DOWNLOADS` (default 3).
