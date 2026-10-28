#!/usr/bin/env bash
# Deploy only the verified B-042 live status and PWA install-button correction.
# Git commits only code once; systemd timer continues to refresh JSON without Git.
set -euo pipefail
REPO=/home/ubuntu/Sites/transport
PUBLIC=/srv/www/transport
BRANCH=fix/maritime-live-pwa-diagnostics-20261028
STAGE=/home/ubuntu/Sites/transport-maritime-stage-20261028

echo "HOST=$(hostname)"
cd "$REPO"
echo "DIR=$PWD"
git status --short
test "$(hostname)" = vps-cd9917e0 || { echo "Unexpected host"; exit 1; }
test "$(git branch --show-current)" = main || { echo "Expected main"; exit 1; }
test -z "$(git status --porcelain)" || { echo "Local Git edits: inspect first"; exit 1; }
test -s "$PUBLIC/index.html" && test -s "$PUBLIC/transport_data.json" ||
  { echo "Published transport files not found"; exit 1; }
test ! -e "$STAGE" || { echo "Existing staging worktree: inspect it first"; exit 1; }

sudo systemctl stop transport-update.timer
trap 'sudo systemctl start transport-update.timer' EXIT
for i in $(seq 1 120); do
  systemctl is-active --quiet transport-update.service || break
  sleep 1
done
if systemctl is-active --quiet transport-update.service; then
  echo "Refresh service still running; leaving it untouched" >&2
  exit 1
fi

git fetch origin main "$BRANCH"
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ||
  { echo "main differs from origin/main; inspect before deploying"; exit 1; }

# Test and generate in a separate checkout before changing live main.
git worktree add --detach "$STAGE" "origin/$BRANCH"
cd "$STAGE"
python3 -m unittest discover -s tests -v
python3 -m compileall -q build_horarios.py transport_updates.py maritime_status.py
python3 build_horarios.py

python3 - <<'PY'
import json
from pathlib import Path
root = Path("output")
payload = json.loads((root / "transport_data.json").read_text(encoding="utf-8"))
meta = payload["meta"]
state = meta.get("maritime", {}).get("status")
assert state in {"operational", "affected"}, f"Maritime API not verified: {state}"
assert payload["data"].get("cadiz-puerto")
assert payload["data"].get("puerto-cadiz")
html = (root / "horarios_tres_ciudades.html").read_text(encoding="utf-8")
assert 'id="boatReference"' in html
print("B-042 official maritime source:", meta["maritime"])
PY

cd "$REPO"
git merge --ff-only "origin/$BRANCH"
git push origin main

# Atomic live publication; AVÍO/Nginx/systemd configuration unchanged.
html_tmp="$(mktemp "$PUBLIC/.index.html.XXXXXX")"
json_tmp="$(mktemp "$PUBLIC/.transport_data.json.XXXXXX")"
trap 'rm -f "$html_tmp" "$json_tmp"; sudo systemctl start transport-update.timer' EXIT
install -m 644 "$STAGE/output/horarios_tres_ciudades.html" "$html_tmp"
install -m 644 "$STAGE/output/transport_data.json" "$json_tmp"
mv -f "$html_tmp" "$PUBLIC/index.html"
mv -f "$json_tmp" "$PUBLIC/transport_data.json"

git worktree remove "$STAGE"
sudo systemctl start transport-update.timer
trap - EXIT
echo "Published https://peluche-ebanache.com/transport/"
echo "15-minute JSON refresh remains enabled; no periodic Git commits."
