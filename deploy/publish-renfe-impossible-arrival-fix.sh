#!/usr/bin/env bash
# Guarded hotfix: reject impossible Renfe arrival predictions and immediately
# sanitize the shared live JSON. Does not modify HTML/PWA/Nginx/AVÍO.
set -euo pipefail
REPO=/home/ubuntu/Sites/transport
PUBLIC=/srv/www/transport/transport_data.json
STAGE="/home/ubuntu/Sites/transport-impossible-rt-stage-$(date +%Y%m%d-%H%M%S)-$$"
cd "$REPO"
echo "HOST=$(hostname) DIR=$PWD"
git status --short
test "$(hostname)" = vps-cd9917e0 || { echo "Wrong VPS"; exit 1; }
test "$(git branch --show-current)" = main || { echo "Expected main checkout"; exit 1; }
test -z "$(git status --porcelain)" || { echo "Local Git changes: inspect before proceeding"; exit 1; }
test -s "$PUBLIC" || { echo "Missing published JSON"; exit 1; }
test -s /srv/www/transport-pwa-root/index.html || { echo "Missing primary transport site"; exit 1; }
git fetch origin main
git merge-base --is-ancestor HEAD origin/main ||
  { echo "Local main diverges from origin; refusing merge"; exit 1; }
git worktree add --detach "$STAGE" origin/main
cleanup(){ git -C "$REPO" worktree remove -f "$STAGE" 2>/dev/null || true; }
trap cleanup EXIT

cd "$STAGE"
python3 -m unittest discover -s tests -v
python3 -m py_compile build_horarios.py transport_updates.py rail_notifications.py deploy/sanitize-impossible-renfe.py
bash -n deploy/*.sh
echo "=== Dry-run validation of live public JSON ==="
PYTHONPATH="$STAGE" python3 deploy/sanitize-impossible-renfe.py --path "$PUBLIC"

cd "$REPO"
sudo systemctl stop transport-update.timer
resume(){ sudo systemctl start transport-update.timer || true; }
trap 'resume; cleanup' EXIT
for i in $(seq 1 120); do
    if ! systemctl is-active --quiet transport-update.service; then break; fi
    sleep 1
done
if systemctl is-active --quiet transport-update.service; then
    echo "Scheduled updater still running: no source changes made" >&2
    exit 1
fi
git merge --ff-only origin/main
echo "=== Immediately remove impossible arrival estimates ==="
PYTHONPATH="$REPO" python3 deploy/sanitize-impossible-renfe.py --apply --path "$PUBLIC"

sudo systemctl start transport-update.timer
trap cleanup EXIT
sudo systemctl start --no-block transport-update.service
echo "Renfe arrival sanity check deployed; JSON cleaned; updater scheduled."
echo "Existing Telegram sent-state preserved; no Nginx/HTML changes."
