#!/usr/bin/env bash
# Stage root-scoped PWA and conditionally install independent HTTPS vhost.
# No changes to the original /transport/ site or its 15-minute updater.
set -euo pipefail
REPO=/home/ubuntu/Sites/transport
PUBLIC=/srv/www/transport-pwa-root
BRANCH=feature/transport-root-subdomain-20261029
STAGE="/home/ubuntu/Sites/transport-subdomain-stage-$(date +%Y%m%d-%H%M%S)-$$"

cd "$REPO"
echo "HOST=$(hostname) DIR=$PWD"
git status --short
test "$(hostname)" = vps-cd9917e0 || { echo "Wrong VPS"; exit 1; }
test "$(git branch --show-current)" = main || { echo "Expected main"; exit 1; }
test -z "$(git status --porcelain)" || { echo "Local changes require inspection"; exit 1; }
test -s /srv/www/transport/transport_data.json || { echo "Original transport JSON missing"; exit 1; }
git fetch origin main "$BRANCH"
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ||
  { echo "Main not synchronized with origin; inspect before continuing"; exit 1; }

git worktree add --detach "$STAGE" "origin/$BRANCH"
cd "$STAGE"
python3 -m unittest discover -s tests -v
python3 -m py_compile deploy/subdomain/build_root.py deploy/subdomain/enable_https.py
mkdir -p "$STAGE/root-pwa"
python3 deploy/subdomain/build_root.py --destination "$STAGE/root-pwa"

# Publish *only* new root-scoped static assets.
sudo install -d -m 755 -o ubuntu -g ubuntu "$PUBLIC"
for name in index.html manifest.json sw.js icon-180.png icon-192-rgb.png icon-512-rgb.png icon-512-maskable.png; do
    temp="$(mktemp "$PUBLIC/.$name.XXXXXX")"
    install -m 644 "$STAGE/root-pwa/$name" "$temp"
    mv -f "$temp" "$PUBLIC/$name"
done
echo "Staged independent root PWA at $PUBLIC"
echo "Existing public /transport/ site and transport_data.json unchanged."

# Require DNS and a certificate covering this subdomain; no speculative
# edits to existing Nginx/AVÍO configuration.
if sudo python3 deploy/subdomain/enable_https.py; then
    echo "HTTPS enabled. Smoke test:"
    curl -fsSI --max-time 15 https://transport.peluche-ebanache.com/
    curl -fsSI --max-time 15 https://transport.peluche-ebanache.com/transport_data.json
    cd "$REPO"
    git merge --ff-only "origin/$BRANCH"
    git push origin main
    echo "Transport root PWA published. Original route remains a backup."
else
    echo "Staging completed but HTTPS is NOT activated."
    echo "Check the DNS CNAME transport -> peluche-ebanache.com and HTTPS certificate."
    echo "Do not reinstall or delete the existing transport site."
fi
