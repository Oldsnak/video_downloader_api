#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export PATH="${HOME}/.deno/bin:${PATH}"

if [ ! -f .env ]; then
  cp .env.codespace .env
fi

mkdir -p downloads

# Bind on all interfaces so GitHub's HTTPS port forward can reach Uvicorn.
exec python -m uvicorn video_downloader_api.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --proxy-headers \
  --forwarded-allow-ips='*'
