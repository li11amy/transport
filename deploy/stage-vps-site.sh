#!/usr/bin/env bash
# Run as ubuntu on VPS after inspecting host, directory and git state.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PUBLIC="/srv/www/transport"

echo "HOST=$(hostname)"
cd "$REPO"
echo "DIR=$PWD"
git status --short
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Refusing to stage: tracked or untracked Git changes require review." >&2
  exit 1
fi

python3 -m unittest discover -s tests -v
python3 -m compileall -q build_horarios.py transport_updates.py
python3 build_horarios.py

# Store only public HTML/JSON and PWA assets outside the source checkout.
sudo install -d -o ubuntu -g ubuntu -m 755 "$PUBLIC"
install -m 644 output/horarios_tres_ciudades.html "$PUBLIC/index.html"
install -m 644 output/transport_data.json "$PUBLIC/transport_data.json"
install -m 644 manifest.json sw.js icon-180.png icon-192.png icon-512.png "$PUBLIC/"

echo "Staged in $PUBLIC; no Nginx, service, or timer configuration changed."
