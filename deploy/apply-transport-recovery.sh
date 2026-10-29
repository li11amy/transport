#!/usr/bin/env bash
# Complete both interrupted transport upgrades in ONE verified deployment.
# Only source code / static PWA assets change. Existing JSON remains until
# the running 15-minute service refreshes it with maritime status.
set -euo pipefail
REPO=/home/ubuntu/Sites/transport
PUBLIC=/srv/www/transport
BRANCH=fix/transport-recovery-20261029
STAGE="/home/ubuntu/Sites/transport-recovery-stage-$(date +%Y%m%d-%H%M%S)-$$"

echo "HOST=$(hostname)"
cd "$REPO"
echo "DIRECTORY=$(pwd)"
git status --short
test "$(hostname)" = vps-cd9917e0 || { echo "Incorrect host; no changes made"; exit 1; }
test "$(git branch --show-current)" = main || { echo "Expected main; no changes made"; exit 1; }
test -z "$(git status --porcelain)" || { echo "Local changes require review; no changes made"; exit 1; }
test -s "$PUBLIC/index.html" && test -s "$PUBLIC/transport_data.json" ||
    { echo "Transport webroot not staged; no changes made"; exit 1; }

# Never touch the old failed staging trees. Each retry gets a fresh worktree.
sudo systemctl stop transport-update.timer
trap 'sudo systemctl start transport-update.timer' EXIT
for attempt in $(seq 1 120); do
    systemctl is-active --quiet transport-update.service || break
    sleep 1
done
if systemctl is-active --quiet transport-update.service; then
    echo "The existing updater has not finished; no source changes made" >&2
    exit 1
fi
git fetch origin main "$BRANCH"
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ||
    { echo "Local main and remote main differ; no merge attempted" >&2; exit 1; }
git worktree add --detach "$STAGE" "origin/$BRANCH"
cd "$STAGE"

python3 -m unittest discover -s tests -v
python3 -m compileall -q build_horarios.py transport_updates.py maritime_status.py tests
bash -n deploy/*.sh

# Produce HTML *without* calling Renfe/CMTBC/Telegram. Output/ is ignored by Git.
python3 - <<'PY'
import json
from pathlib import Path
from build_horarios import HTML
payload=json.loads(Path("/srv/www/transport/transport_data.json").read_text(encoding="utf-8"))
assert isinstance(payload["data"],dict) and len(payload["data"]) == 6, "Expected six city pairs"
assert isinstance(payload["meta"],dict) and payload["meta"].get("checked_at"), "Missing update timestamp"
for name in ("icon-192-rgb.png","icon-512-rgb.png","icon-512-maskable.png"):
    raw=Path(name).read_bytes()
    assert raw[:8]==b"\x89PNG\r\n\x1a\n" and raw[25]==2, "Invalid truecolor PNG: "+name
as_js=lambda value:json.dumps(value,ensure_ascii=False).replace("<","\\u003c")
page=(HTML.replace("__TRANSPORT_DATA__",as_js(payload["data"]))
          .replace("__SERVICE_META__",as_js(payload["meta"]))
          .replace("__UPDATED__",""))
assert "manifest.json?v=2" in page and 'id="boatReference"' in page
output=Path("output")
output.mkdir(parents=True,exist_ok=True)
(output/"pwa-recovery-index.html").write_text(page,encoding="utf-8")
print("PWA shell ready; old site and JSON still untouched",flush=True)
PY

# Smoke official maritime BOM decoding without mutating the public timetable.
python3 - <<'PY'
from datetime import datetime
from zoneinfo import ZoneInfo
from maritime_status import live_maritime_changes
now=datetime.now(ZoneInfo("Europe/Madrid"))
events,errors=live_maritime_changes({},now,statistics={})
if errors:
    print("Warning: maritime API currently unavailable; updater will show yellow:",errors)
else:
    print("Maritime API BOM and metadata decoded successfully")
PY

cd "$REPO"
# The feature branch was prepared from current main; no force-push or reset.
git merge --ff-only "origin/$BRANCH"
git push origin main

# Publish new icons/manifest/service worker first and HTML last, atomically.
for name in icon-192-rgb.png icon-512-rgb.png icon-512-maskable.png manifest.json sw.js; do
    temp="$(mktemp "$PUBLIC/.$name.XXXXXX")"
    install -m 644 "$STAGE/$name" "$temp"
    mv -f "$temp" "$PUBLIC/$name"
done
temp="$(mktemp "$PUBLIC/.index.html.XXXXXX")"
install -m 644 "$STAGE/output/pwa-recovery-index.html" "$temp"
mv -f "$temp" "$PUBLIC/index.html"

git worktree remove "$STAGE"
sudo systemctl start transport-update.timer
trap - EXIT
sudo systemctl start --no-block transport-update.service
echo "Transport PWA and maritime status published at https://peluche-ebanache.com/transport/"
echo "Timer still refreshes JSON; no periodic Git commits."
