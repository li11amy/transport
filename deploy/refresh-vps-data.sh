#!/usr/bin/env bash
# Refresh timetable data only. Git, Docker and the HTML shell are untouched.
set -euo pipefail

REPO="/home/ubuntu/Sites/transport"
PUBLIC="/srv/www/transport"
cd "$REPO"

exec 9>/tmp/transport-refresh-data.lock
flock -n 9 || exit 0
test -d "$PUBLIC" || { echo "Missing transport public directory" >&2; exit 1; }
test -f "$PUBLIC/index.html" || { echo "Transport HTML shell is not installed" >&2; exit 1; }

python3 build_horarios.py --data-only
test -s output/transport_data.json

# Write a complete JSON first and atomically replace the public data.
tmp="$(mktemp "$PUBLIC/.transport_data.json.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
install -m 644 output/transport_data.json "$tmp"
mv -f "$tmp" "$PUBLIC/transport_data.json"
trap - EXIT
echo "Transport JSON refreshed without Git commits: $(date -Is)"
