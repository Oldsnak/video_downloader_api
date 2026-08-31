#!/usr/bin/env bash
set -euo pipefail

sudo apt-get update
sudo apt-get install -y --no-install-recommends ffmpeg

if ! command -v deno >/dev/null 2>&1; then
  curl -fsSL https://deno.land/install.sh | sh
fi

export PATH="${HOME}/.deno/bin:${PATH}"

python -m pip install --upgrade pip
pip install -r requirements.txt

mkdir -p downloads
if [ ! -f .env ]; then
  cp .env.codespace .env
fi

echo "Codespace setup complete. ffmpeg=$(command -v ffmpeg) deno=$(command -v deno || echo "${HOME}/.deno/bin/deno")"
