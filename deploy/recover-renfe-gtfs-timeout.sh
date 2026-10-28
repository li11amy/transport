#!/usr/bin/env bash
# Recover a Renfe upgrade whose first build timed out at siu.cmtbc.es.
# This keeps the verified already-staged squash changes and patches ONLY
# if the Git index exactly matches that previous feature snapshot.
set -euo pipefail

REPO=/home/ubuntu/Sites/transport
PUBLIC=/srv/www/transport
BRANCH=fix/renfe-tripid-gtfs-20261028
PREVIOUS_FEATURE=37d6d776c27af6d764842aae2e9e5a266a7c2e02

echo "Host: $(hostname)"
cd "$REPO"
echo "Directory: $(pwd)"
git status --short
test "$(hostname)" = "vps-cd9917e0" ||
    { echo "Unexpected VPS host. No changes made."; exit 1; }
test "$(git branch --show-current)" = "main" ||
    { echo "Not on main. No changes made."; exit 1; }
test -f "$PUBLIC/index.html" && test -f "$PUBLIC/transport_data.json" ||
    { echo "Public transport site is missing."; exit 1; }
git diff --quiet ||
    { echo "Unstaged local edits present. Inspect them first."; exit 1; }
test -z "$(git ls-files --others --exclude-standard)" ||
    { echo "Untracked source files present. Inspect them first."; exit 1; }
git cat-file -e "$PREVIOUS_FEATURE^{tree}" ||
    { echo "Prior feature tree absent. No changes made."; exit 1; }
old_tree="$(git rev-parse "$PREVIOUS_FEATURE^{tree}")"
current_index="$(git write-tree)"
if [[ "$current_index" != "$old_tree" ]]; then
    echo "Staged files do not exactly equal the expected previous squash."
    echo "Expected: $old_tree"
    echo "Actual:   $current_index"
    echo "No changes made; inspect git status and staged diff." >&2
    exit 1
fi

sudo systemctl stop transport-update.timer
trap 'sudo systemctl start transport-update.timer' EXIT
for _ in $(seq 1 150); do
    systemctl is-active --quiet transport-update.service || break
    sleep 1
done
if systemctl is-active --quiet transport-update.service; then
    echo "Transport updater is still running; not touching its files." >&2
    exit 1
fi

git fetch origin "$BRANCH"
# Patch previous staged feature tree to the current reviewed feature tree.
# git apply --index refuses changes if tracked files have drifted.
git diff --binary "$PREVIOUS_FEATURE" FETCH_HEAD | git apply --index
python3 -m unittest discover -s tests -v
python3 -m compileall -q build_horarios.py transport_updates.py renfe_schedule.py renfe_static_gtfs.py
python3 build_horarios.py

python3 - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path("output/transport_data.json").read_text(encoding="utf-8"))
sources = payload.get("meta", {}).get("renfe_schedule", {})
print("Official Renfe schedule:", json.dumps(sources, ensure_ascii=False))
for line in ("C-1", "MD"):
    if sources.get(line, {}).get("official_rows", 0) < 1:
        raise RuntimeError("No official timetable from Renfe " + line)
PY

git commit -m "Use official Renfe GTFS trains and resilient CMTBC bus fallback"
git push origin main

# Publish complete data atomically. No Nginx or AVÍO modifications.
html_tmp="$(mktemp "$PUBLIC/.index.html.XXXXXX")"
json_tmp="$(mktemp "$PUBLIC/.transport_data.json.XXXXXX")"
trap 'rm -f "$html_tmp" "$json_tmp"; sudo systemctl start transport-update.timer' EXIT
install -m 644 output/horarios_tres_ciudades.html "$html_tmp"
install -m 644 output/transport_data.json "$json_tmp"
mv "$html_tmp" "$PUBLIC/index.html"
mv "$json_tmp" "$PUBLIC/transport_data.json"

sudo systemctl start transport-update.timer
trap - EXIT
sudo systemctl start transport-update.service
systemctl show transport-update.service -p ActiveState -p Result
echo "Published https://peluche-ebanache.com/transport/ without recurring Git commits."
