#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export PATH="${HOME}/.deno/bin:${PATH}"

# Always use the Codespace env (no Redis/Celery). A leftover .env from
# an earlier start would otherwise leave jobs stuck in "queued".
cp .env.codespace .env

# Codespaces secrets (repo or user) override the copied file without committing
# proxy passwords. Supported: YTDLP_PROXIES or USER+PASSWORD+ENDPOINTS.
append_secret() {
  local key="$1"
  local value
  value="$(printenv "${key}" || true)"
  if [ -n "${value}" ]; then
    printf '\n%s=%s\n' "${key}" "${value}" >> .env
  fi
}
append_secret YTDLP_PROXIES
append_secret YTDLP_PROXY
append_secret YTDLP_PROXY_USER
append_secret YTDLP_PROXY_PASSWORD
append_secret YTDLP_PROXY_ENDPOINTS

# Secrets are sometimes missing from postStart's environment. Keep the last
# known proxy block so a restart does not drop Webshare and send YouTube
# out the Codespace IP (instant bot check).
if ! grep -q '^YTDLP_PROXY_ENDPOINTS=' .env && ! grep -q '^YTDLP_PROXIES=' .env; then
  if [ -f .proxy.env ]; then
    cat .proxy.env >> .env
  fi
else
  grep -E '^YTDLP_PROXY' .env > .proxy.env || true
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
