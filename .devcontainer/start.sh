#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export PATH="${HOME}/.deno/bin:${PATH}"

if [ ! -f .env ]; then
  cp .env.codespace .env
fi

mkdir -p downloads

python -m uvicorn video_downloader_api.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --proxy-headers \
  --forwarded-allow-ips='*' &
API_PID=$!

for _ in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:8000/api/v1/health" >/dev/null; then
    break
  fi
  sleep 1
done

# GitHub's *.app.github.dev forward stays cookie-gated (HTTP 401) for phones.
# A Cloudflare quick tunnel gives a public HTTPS URL the Flutter app can use.
cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8000 > /tmp/cloudflared.log 2>&1 &

PUBLIC_URL=""
for _ in $(seq 1 40); do
  PUBLIC_URL="$(grep -oE 'https://[A-Za-z0-9.-]+\.trycloudflare.com' /tmp/cloudflared.log | head -n 1 || true)"
  if [ -n "${PUBLIC_URL}" ]; then
    printf '%s\n' "${PUBLIC_URL}" > .codespace-public-url
    echo "PUBLIC_API_URL=${PUBLIC_URL}"
    break
  fi
  sleep 1
done

wait "${API_PID}"
