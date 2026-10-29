#!/usr/bin/env bash
# Publish passenger-friendly Renfe alerts WITHOUT refetching/touching timetable JSON.
# Safely advance source main, preserve 15-minute timer and patch two HTML shells.
set -euo pipefail
REPO=/home/ubuntu/Sites/transport
BRANCH_MAIN=main
STAGE="/home/ubuntu/Sites/transport-passenger-alerts-stage-$(date +%Y%m%d-%H%M%S)-$$"

cd "$REPO"
echo "HOST=$(hostname) DIR=$PWD"
git status --short
test "$(hostname)" = vps-cd9917e0 || { echo "Unexpected VPS"; exit 1; }
test "$(git branch --show-current)" = "$BRANCH_MAIN" || {
    echo "Expected source main, not a feature branch"; exit 1; }
test -z "$(git status --porcelain)" || {
    echo "Uncommitted changes: stop and inspect, nothing was overwritten"; exit 1; }
test -s /srv/www/transport/index.html &&
test -s /srv/www/transport-pwa-root/index.html &&
test -s /srv/www/transport/transport_data.json || {
    echo "Missing one or more installed transport files"; exit 1; }

# No risky git pull/restore: only fast-forward after checking code in a
# detached, unique staging worktree.
git fetch origin main
git merge-base --is-ancestor HEAD origin/main || {
    echo "Local main has diverged from GitHub; refusing to replace any work"; exit 1; }
git worktree add --detach "$STAGE" origin/main
cleanup() { git -C "$REPO" worktree remove -f "$STAGE" 2>/dev/null || true; }
trap cleanup EXIT
cd "$STAGE"
python3 -m unittest discover -s tests -v
python3 -m compileall -q build_horarios.py transport_updates.py deploy/patch-public-rail-source.py
bash -n deploy/*.sh

# Validate BOTH installed site shells before changing any source or service.
PYTHONPATH="$STAGE" python3 deploy/patch-public-rail-source.py

cd "$REPO"
sudo systemctl stop transport-update.timer
resume() { sudo systemctl start transport-update.timer || true; }
trap 'resume; cleanup' EXIT
for i in $(seq 1 120); do
    systemctl is-active --quiet transport-update.service || break
    sleep 1
done
if systemctl is-active --quiet transport-update.service; then
    echo "Updater is still busy; refusing to modify source while running" >&2
    exit 1
fi
git merge --ff-only origin/main

# Patches just the outdated public Renfe source-link section. The unchanged
# JSON is still shared by both addresses and the transport timer.
python3 deploy/patch-public-rail-source.py --apply
sudo systemctl start transport-update.timer
trap cleanup EXIT
sudo systemctl start --no-block transport-update.service
echo "Passenger-friendly Renfe alerts published; data refresh scheduled."
echo "No GTFS .json URLs or link-preview attachment cards in new Telegram alerts."
