#!/usr/bin/env bash
# Apply ONLY header, legend and install-control UI. Keep public JSON, backend and timer.
set -euo pipefail
REPO="/home/ubuntu/Sites/transport"
PUBLIC="/srv/www/transport"
BRANCH="feature/transport-header-pwa-install-20261028"
echo "Host: $(hostname)"
cd "$REPO"
echo "Directory: $PWD"
git status --short
test "$(hostname)" = "vps-cd9917e0" ||
  { echo "Wrong host, refusing to deploy"; exit 1; }
test "$(git branch --show-current)" = "main" ||
  { echo "Not on main, refusing to deploy"; exit 1; }
test -z "$(git status --porcelain)" ||
  { echo "Local changes present, refusing to deploy"; exit 1; }
test -s "$PUBLIC/index.html" && test -s "$PUBLIC/transport_data.json" ||
  { echo "Existing transport site not found"; exit 1; }

# Do not update Python code under an in-flight updater.
sudo systemctl stop transport-update.timer
trap 'sudo systemctl start transport-update.timer' EXIT
for i in $(seq 1 90); do
    systemctl is-active --quiet transport-update.service || break
    sleep 1
done
if systemctl is-active --quiet transport-update.service; then
    echo "Updater is running; no code changes made" >&2
    exit 1
fi

git fetch origin main "$BRANCH"
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ||
  { echo "Local main and origin/main differ: inspect before deploying"; exit 1; }
git merge --ff-only "origin/$BRANCH"
python3 -m unittest discover -s tests -v
python3 -m compileall -q build_horarios.py

# Rebuild only the static HTML shell from the LAST PUBLISHED JSON.
# No CMTBC/Renfe API calls, no Telegram sends, and no JSON file modifications.
python3 - <<'PY'
import json
import os
import tempfile
from pathlib import Path
from build_horarios import HTML

public = Path("/srv/www/transport")
payload = json.loads((public / "transport_data.json").read_text(encoding="utf-8"))
data, meta = payload["data"], payload["meta"]
assert isinstance(data, dict) and len(data) >= 6, "Missing timetable data"
assert isinstance(meta, dict) and meta.get("checked_at"), "Missing timestamp"

def js_json(value):
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")

page = (HTML.replace("__TRANSPORT_DATA__", js_json(data))
            .replace("__SERVICE_META__", js_json(meta))
            .replace("__UPDATED__", ""))
assert "installButton" in page and "beforeinstallprompt" in page and "trainReference" in page
assert "__TRANSPORT_DATA__" not in page and "__SERVICE_META__" not in page

with tempfile.NamedTemporaryFile("w", encoding="utf-8",
                                 prefix=".index.html.", dir=public,
                                 delete=False) as handle:
    temp_path = Path(handle.name)
    handle.write(page)
try:
    os.chmod(temp_path, 0o644)
    os.replace(temp_path, public / "index.html")
finally:
    temp_path.unlink(missing_ok=True)
print("Published PWA header UI:", public / "index.html")
PY

git push origin main
sudo systemctl start transport-update.timer
trap - EXIT
echo "https://peluche-ebanache.com/transport/ — UI/PWA install control updated. JSON timer unchanged."
