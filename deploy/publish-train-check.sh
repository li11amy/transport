#!/usr/bin/env bash
# Guarded deploy of Telegram train check, transport PWA button and bot poller.
set -euo pipefail
REPO=/home/ubuntu/Sites/transport
STAGE="/home/ubuntu/Sites/transport-train-deploy-$(date +%Y%m%d-%H%M%S)-$$"
cd "$REPO"
echo "HOST=$(hostname) DIRECTORY=$PWD"
git status --short
test "$(hostname)" = vps-cd9917e0 || { echo "Unexpected host"; exit 1; }
test "$(git branch --show-current)" = main || { echo "Expected main"; exit 1; }
test -z "$(git status --porcelain)" || { echo "Local changes need review"; exit 1; }
test -s /srv/www/transport/transport_data.json || { echo "Live timetable JSON missing"; exit 1; }
test -f /srv/www/transport-pwa-root/index.html || { echo "PWA shell missing"; exit 1; }
test -f /home/ubuntu/.config/transport-update.env || { echo "Bot environment missing"; exit 1; }
git fetch origin main
git merge-base --is-ancestor HEAD origin/main || { echo "Local commit diverged"; exit 1; }
git worktree add --detach "$STAGE" origin/main
cleanup() { git -C "$REPO" worktree remove -f "$STAGE" 2>/dev/null || true; }
trap cleanup EXIT
cd "$STAGE"
python3 -m unittest discover -s tests -q
python3 -m compileall -q telegram_train_check.py build_horarios.py tests
bash -n deploy/*.sh
python3 deploy/patch-train-telegram.py
cd "$REPO"
# Only the source-check service is new. No transport-update.timer restart or
# notification-state clearing. Installed shells are patched atomically.
git merge --ff-only origin/main
python3 deploy/patch-train-telegram.py --apply
sudo install -m 0644 deploy/transport-train-check.service /etc/systemd/system/transport-train-check.service
sudo systemctl daemon-reload
sudo systemctl enable --now transport-train-check.service
sudo systemctl is-active --quiet transport-train-check.service
echo "On-demand Telegram train check installed; transport updater unchanged."
