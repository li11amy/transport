#!/usr/bin/env bash
# Publish verified strike warning NOW without refetching upstream schedules.
set -euo pipefail
REPO=/home/ubuntu/Sites/transport
PUBLIC=/srv/www/transport
BRANCH=fix/renfe-strike-29oct-2026
STAGE="/home/ubuntu/Sites/transport-strike-stage-$(date +%Y%m%d-%H%M%S)-$$"
cd "$REPO"
echo "HOST=$(hostname) DIR=$PWD"
git status --short
test "$(hostname)" = "vps-cd9917e0" || { echo "Unexpected host"; exit 1; }
test "$(git branch --show-current)" = "main" || { echo "Expected main"; exit 1; }
test -z "$(git status --porcelain)" || { echo "Git has local changes; inspect first"; exit 1; }
test -s "$PUBLIC/index.html" && test -s "$PUBLIC/transport_data.json" || { echo "Missing transport webroot"; exit 1; }

sudo systemctl stop transport-update.timer
trap 'sudo systemctl start transport-update.timer' EXIT
for i in $(seq 1 120); do
    systemctl is-active --quiet transport-update.service || break
    sleep 1
done
if systemctl is-active --quiet transport-update.service; then
    echo "Updater is still active; refusing merge" >&2
    exit 1
fi

git fetch origin main "$BRANCH"
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" || { echo "Local main differs from remote main; refusing merge"; exit 1; }
git worktree add --detach "$STAGE" "origin/$BRANCH"
cd "$STAGE"
python3 -m unittest discover -s tests -v
python3 -m compileall -q build_horarios.py transport_updates.py source_alerts.py
bash -n deploy/*.sh

python3 - <<'PY'
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from build_horarios import HTML
from source_alerts import apply_source_alerts
public=Path("/srv/www/transport")
payload=json.loads((public/"transport_data.json").read_text(encoding="utf-8"))
now=datetime.now(ZoneInfo("Europe/Madrid"))
assert payload["meta"].get("date")==now.date().isoformat(), "Public JSON does not describe today; refusing stale reuse"
events,summaries=apply_source_alerts(payload["data"],now)
if now.date().isoformat()=="2026-10-29":
    assert len(events)==1 and summaries[0]["affected_rows"]>0, "Strike not applied to train rows"
payload["meta"]["official_alerts"]=summaries
out=Path("output")
out.mkdir(exist_ok=True)
(out/"strike-data.json").write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
js=lambda value:json.dumps(value,ensure_ascii=False).replace("<","\\u003c")
html=(HTML.replace("__TRANSPORT_DATA__",js(payload["data"]))
          .replace("__SERVICE_META__",js(payload["meta"]))
          .replace("__UPDATED__",""))
assert 'id="officialAlerts"' in html
(out/"strike-index.html").write_text(html,encoding="utf-8")
print("Prepared official strike warnings:",summaries,flush=True)
PY

cd "$REPO"
git merge --ff-only "origin/$BRANCH"
git push origin main
# Publish JSON first and HTML second, both atomic.
for file in "strike-data.json transport_data.json" "strike-index.html index.html"; do
    set -- $file
    tmp="$(mktemp "$PUBLIC/.$2.XXXXXX")"
    install -m 644 "$STAGE/output/$1" "$tmp"
    mv -f "$tmp" "$PUBLIC/$2"
done
git worktree remove "$STAGE" || echo "Temporary worktree retained; review later"
sudo systemctl start transport-update.timer
trap - EXIT
sudo systemctl start --no-block transport-update.service
echo "Official strike warning published: https://peluche-ebanache.com/transport/"
