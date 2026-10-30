#!/usr/bin/env bash
# One-time safe update of Renfe Telegram notification policy, not HTML.
# The existing JSON-only 15-minute timer and Telegram credentials stay intact.
set -euo pipefail
REPO=/home/ubuntu/Sites/transport
STAGE="/home/ubuntu/Sites/transport-rail-alerts-stage-$(date +%Y%m%d-%H%M%S)-$$"
cd "$REPO"
echo "HOST=$(hostname) DIR=$PWD"
git status --short
test "$(hostname)" = vps-cd9917e0 || { echo "Unexpected VPS hostname"; exit 1; }
test "$(git branch --show-current)" = main || { echo "Expected main branch"; exit 1; }
test -z "$(git status --porcelain)" || { echo "Local edits found; refusing merge"; exit 1; }
test -s /srv/www/transport/transport_data.json || { echo "Shared public JSON missing"; exit 1; }
git fetch origin main
git merge-base --is-ancestor HEAD origin/main ||
  { echo "Local main diverged from GitHub; refusing merge"; exit 1; }

git worktree add --detach "$STAGE" origin/main
cleanup(){
    git -C "$REPO" worktree remove -f "$STAGE" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cd "$STAGE"
python3 -m unittest discover -s tests -v
python3 -m py_compile transport_updates.py rail_notifications.py build_horarios.py
bash -n deploy/*.sh

# Stop scheduling new refresh jobs, then wait for an existing refresh to finish.
cd "$REPO"
sudo systemctl stop transport-update.timer
resume(){ sudo systemctl start transport-update.timer || true; }
trap 'resume; cleanup' EXIT
for i in $(seq 1 120); do
    if ! systemctl is-active --quiet transport-update.service; then break; fi
    sleep 1
done
if systemctl is-active --quiet transport-update.service; then
    echo "Transport updater still active; refusing source update" >&2
    exit 1
fi
git merge --ff-only origin/main

# Old Telegram deduplication state is preserved: the upgraded policy migrates
# prior per-route Renfe alerts and prevents a first-run notification storm.
sudo systemctl start transport-update.timer
trap cleanup EXIT
sudo systemctl start --no-block transport-update.service
echo "Anti-spam Renfe policy installed. No HTML, Nginx, Certbot or Git data commits."
echo "Notification state retained: output/service_change_notifications.json"
