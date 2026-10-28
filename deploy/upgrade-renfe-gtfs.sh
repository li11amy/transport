#!/usr/bin/env bash
# Apply verified Renfe GTFS timetable correction on the transport VPS.
# Does not alter AVÍO, Nginx, Docker or the systemd timer configuration.
set -euo pipefail

REPO="/home/ubuntu/Sites/transport"
PUBLIC="/srv/www/transport"
BRANCH="fix/renfe-tripid-gtfs-20261028"

echo "HOST=$(hostname)"
cd "$REPO"
echo "DIR=$PWD"
git status --short
test "$(hostname)" = "vps-cd9917e0" || { echo "Wrong VPS host"; exit 1; }
test "$(git branch --show-current)" = "main" || { echo "Expected main branch"; exit 1; }
test -z "$(git status --porcelain)" || { echo "Uncommitted changes: inspect before continuing"; exit 1; }
test -f "$PUBLIC/index.html" && test -f "$PUBLIC/transport_data.json" ||
  { echo "Transport Nginx webroot is missing"; exit 1; }

sudo systemctl stop transport-update.timer
trap 'sudo systemctl start transport-update.timer' EXIT
for i in $(seq 1 120); do
    if ! systemctl is-active --quiet transport-update.service; then break; fi
    sleep 1
done
if systemctl is-active --quiet transport-update.service; then
    echo "Previous refresh is still running; code not changed" >&2
    exit 1
fi

git fetch origin
git merge --squash "origin/$BRANCH"
python3 -m unittest discover -s tests -v
python3 -m compileall -q build_horarios.py transport_updates.py renfe_static_gtfs.py renfe_schedule.py
python3 build_horarios.py

python3 - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path("output/transport_data.json").read_text(encoding="utf-8"))
sources = payload["meta"].get("renfe_schedule", {})
print("Renfe GTFS official timetable:", json.dumps(sources, ensure_ascii=False))
assert sources.get("C-1", {}).get("official_rows", 0) > 0, "No official C-1 schedule"
assert sources.get("MD", {}).get("official_rows", 0) > 0, "No official MD schedule"
PY

git commit -m "Use official Renfe GTFS schedules and date-safe realtime updates"
git push origin main

# Atomic replacements so Nginx readers never observe partial files.
new_html="$(mktemp "$PUBLIC/.index.html.XXXXXX")"
new_json="$(mktemp "$PUBLIC/.transport_data.json.XXXXXX")"
trap 'rm -f "$new_html" "$new_json"; sudo systemctl start transport-update.timer' EXIT
install -m 644 output/horarios_tres_ciudades.html "$new_html"
install -m 644 output/transport_data.json "$new_json"
mv -f "$new_html" "$PUBLIC/index.html"
mv -f "$new_json" "$PUBLIC/transport_data.json"

sudo systemctl start transport-update.timer
trap - EXIT
sudo systemctl start transport-update.service
systemctl show transport-update.service -p ActiveState -p Result
echo "Deployed: https://peluche-ebanache.com/transport/"
