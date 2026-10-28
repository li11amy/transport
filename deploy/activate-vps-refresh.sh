#!/usr/bin/env bash
# Run ONLY after staged /transport/ HTML + JSON return HTTP 200 via Nginx.
set -euo pipefail

REPO="/home/ubuntu/Sites/transport"
BRANCH="feature/standalone-vps-transport-20261028"
OVERRIDE="/etc/systemd/system/transport-update.service.d/override.conf"

echo "HOST=$(hostname)"
cd "$REPO"
echo "DIR=$PWD"
git status --short
if [[ -n "$(git status --porcelain)" ]]; then
    echo "Uncommitted changes present. Refusing to activate." >&2
    exit 1
fi

curl --fail --silent --show-error --max-time 15 https://peluche-ebanache.com/transport/ >/dev/null
curl --fail --silent --show-error --max-time 15 https://peluche-ebanache.com/transport/transport_data.json >/dev/null

# Stop the original GitHub Pages publisher before bringing the new updater live.
sudo systemctl stop transport-update.timer
trap 'sudo systemctl start transport-update.timer' EXIT
for _ in $(seq 1 60); do
    state="$(systemctl show transport-update.service -p ActiveState --value)"
    [[ "$state" == "inactive" || "$state" == "failed" ]] && break
    sleep 1
done
state="$(systemctl show transport-update.service -p ActiveState --value)"
if [[ "$state" != "inactive" && "$state" != "failed" ]]; then
    echo "Transport service is still active; refusing to change Git checkout." >&2
    exit 1
fi

git fetch origin
git merge --ff-only origin/main
git merge --no-ff --no-edit "origin/$BRANCH"
python3 -m unittest discover -s tests -v
python3 -m compileall -q build_horarios.py transport_updates.py

if sudo test -e "$OVERRIDE"; then
    if ! sudo cmp -s deploy/transport-update-service.override.conf "$OVERRIDE"; then
        echo "Existing systemd override differs. Refusing to replace." >&2
        exit 1
    fi
else
    sudo install -D -m 644 deploy/transport-update-service.override.conf "$OVERRIDE"
fi

sudo systemctl daemon-reload
sudo systemctl start transport-update.timer
trap - EXIT
sudo systemctl start transport-update.service
systemctl show transport-update.service -p ActiveState -p Result --no-pager
systemctl cat transport-update.service
git push origin main
echo "Activated JSON-only updater; no periodic Git commits."
