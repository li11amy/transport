#!/usr/bin/env bash
# Publish observational RadarDeTrenes station-board diagnostics only.
# Does NOT promote Radar/Renfe board estimates into trusted live times,
# Telegram, published HTML or operational GTFS replacement.
set -euo pipefail
REPO=/home/ubuntu/Sites/transport
STAGE="/home/ubuntu/Sites/transport-radar-stage-$(date +%Y%m%d-%H%M%S)-$$"

cd "$REPO"
echo "HOST=$(hostname) DIRECTORY=$PWD"
git status --short
test "$(hostname)" = vps-cd9917e0 || { echo "Unexpected host"; exit 1; }
test "$(git branch --show-current)" = main || { echo "Expected main"; exit 1; }
test -z "$(git status --porcelain)" || { echo "Local changes need review"; exit 1; }
test -s /srv/www/transport/transport_data.json || {
  echo "Shared live JSON missing"; exit 1;
}
git fetch origin main
git merge-base --is-ancestor HEAD origin/main || {
  echo "Local history diverged from GitHub; refusing update"; exit 1;
}
git worktree add --detach "$STAGE" origin/main
cleanup() { git -C "$REPO" worktree remove -f "$STAGE" 2>/dev/null || true; }
trap cleanup EXIT

cd "$STAGE"
python3 -m unittest discover -s tests -v
python3 -m compileall -q radar_shadow.py transport_updates.py build_horarios.py
bash -n deploy/*.sh

cd "$REPO"
sudo systemctl stop transport-update.timer
resume() { sudo systemctl start transport-update.timer || true; }
trap 'resume; cleanup' EXIT
for i in $(seq 1 120); do
  systemctl is-active --quiet transport-update.service || break
  sleep 1
done
if systemctl is-active --quiet transport-update.service; then
  echo "Running transport refresh has not finished; source unchanged" >&2
  exit 1
fi
git merge --ff-only origin/main
sudo systemctl start transport-update.timer
trap cleanup EXIT
sudo systemctl start --no-block transport-update.service
echo "Secondary station-board diagnostic installed. Site remains Renfe-primary."
echo "Inspect only after updater finishes: output/service_change_report.json"
echo "No new passenger alerts, automatic time overrides or Git data commits."
