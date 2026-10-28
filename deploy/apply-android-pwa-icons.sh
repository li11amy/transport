#!/usr/bin/env bash
# Publish new Android PWA icons without rebuilding transport data.
# Does not touch AVÍO, Docker, Nginx, DNS or the 15-minute JSON timer.
set -euo pipefail
REPO=/home/ubuntu/Sites/transport
PUBLIC=/srv/www/transport
BRANCH=fix/android-transport-pwa-install-20261028
PREP=/home/ubuntu/Sites/transport-pwa-icons-stage

echo "HOST=$(hostname)"
cd "$REPO"
echo "DIRECTORY=$PWD"
git status --short
test "$(hostname)" = vps-cd9917e0 || { echo "Wrong host; no changes made"; exit 1; }
test "$(git branch --show-current)" = main || { echo "Unexpected Git branch"; exit 1; }
test -z "$(git status --porcelain)" || { echo "Git working directory is not clean"; exit 1; }
test -f "$PUBLIC/index.html" && test -f "$PUBLIC/transport_data.json" || { echo "Public transport site is absent"; exit 1; }
test ! -e "$PREP" || { echo "Staging directory exists; inspect it"; exit 1; }

sudo systemctl stop transport-update.timer
trap 'sudo systemctl start transport-update.timer' EXIT
for i in $(seq 1 90); do
    systemctl is-active --quiet transport-update.service || break
    sleep 1
done
if systemctl is-active --quiet transport-update.service; then
    echo "Refresh service is still running; no changes made" >&2
    exit 1
fi

git fetch origin main "$BRANCH"
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ||
    { echo "Local main and origin/main differ; inspect before updating"; exit 1; }
git worktree add --detach "$PREP" "origin/$BRANCH"
cd "$PREP"
python3 -m unittest discover -s tests -v
python3 -m compileall -q build_horarios.py tests

# Render only HTML using current published data; do not call CMTBC/Renfe.
python3 - <<'PY'
import json
from pathlib import Path
from build_horarios import HTML
payload=json.loads(Path("/srv/www/transport/transport_data.json").read_text(encoding="utf-8"))
assert isinstance(payload["data"],dict) and len(payload["data"])>=6
assert payload["meta"].get("checked_at")
j=lambda x:json.dumps(x,ensure_ascii=False).replace("<","\\u003c")
page=(HTML.replace("__TRANSPORT_DATA__",j(payload["data"]))
          .replace("__SERVICE_META__",j(payload["meta"]))
          .replace("__UPDATED__",""))
assert "manifest.json?v=2" in page
Path("output/pwa-install-index.html").write_text(page,encoding="utf-8")
print("Prepared HTML without network calls",flush=True)
PY

cd "$REPO"
git merge --ff-only "origin/$BRANCH"
git push origin main

# Atomic replacement of assets, HTML LAST. Index and JSON are independent.
for name in icon-192-rgb.png icon-512-rgb.png icon-512-maskable.png manifest.json sw.js; do
    candidate="$(mktemp "$PUBLIC/.$name.XXXXXX")"
    install -m 644 "$PREP/$name" "$candidate"
    mv -f "$candidate" "$PUBLIC/$name"
done
candidate="$(mktemp "$PUBLIC/.index.html.XXXXXX")"
install -m 644 "$PREP/output/pwa-install-index.html" "$candidate"
mv -f "$candidate" "$PUBLIC/index.html"

git worktree remove "$PREP"
sudo systemctl start transport-update.timer
trap - EXIT
echo "PWA assets updated: https://peluche-ebanache.com/transport/"
echo "No timetable or timer changes made."
