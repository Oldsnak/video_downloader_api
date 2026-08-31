#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

sudo apt-get update
sudo apt-get install -y --no-install-recommends ffmpeg

if ! command -v deno >/dev/null 2>&1; then
  curl -fsSL https://deno.land/install.sh | sh
fi

export PATH="${HOME}/.deno/bin:${PATH}"

python -m pip install --upgrade pip
pip install -r requirements.txt

if ! command -v cloudflared >/dev/null 2>&1; then
  sudo curl -fsSL -o /usr/local/bin/cloudflared \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
  sudo chmod +x /usr/local/bin/cloudflared
fi

mkdir -p downloads
if [ ! -f .env ]; then
  cp .env.codespace .env
fi

echo "Codespace setup complete. ffmpeg=$(command -v ffmpeg) deno=$(command -v deno || echo "${HOME}/.deno/bin/deno")"
