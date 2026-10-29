#!/usr/bin/env bash
# Reproduce HTTP-01 404 without contacting Let's Encrypt.
# Only an owned temporary port-80 vhost and a unique probe file are created.
set -euo pipefail
REPO=/home/ubuntu/Sites/transport
ROOT=/srv/www/transport-pwa-root
DOMAIN=transport.peluche-ebanache.com
cd "$REPO"
printf 'HOST=%s DIR=%s\n' "$(hostname)" "$PWD"
git status --short
test "$(hostname)" = vps-cd9917e0 || { echo 'Wrong VPS'; exit 1; }
test "$(git branch --show-current)" = main || { echo 'Expected main'; exit 1; }
test -z "$(git status --porcelain)" || { echo 'Uncommitted changes: inspect first'; exit 1; }
test -s "$ROOT/index.html" || { echo 'Subdomain PWA has not been staged'; exit 1; }
git fetch origin feature/transport-root-subdomain-20261029
bootstrap="deploy/subdomain/bootstrap_http.py"
git show "FETCH_HEAD:$bootstrap" | sudo python3 - setup

probe="transport-dcv-probe-$(date +%s)-$$"
mkdir -p "$ROOT/.well-known/acme-challenge"
path="$ROOT/.well-known/acme-challenge/$probe"
printf 'ok-%s\n' "$probe" > "$path"
chmod 644 "$path"
cleanup(){
    rm -f "$path"
    git show "FETCH_HEAD:$bootstrap" | sudo python3 - rollback ||
      echo 'Temporary HTTP vhost needs manual review'
}
trap cleanup EXIT

echo '=== FILE ACCESS PERMISSIONS ==='
namei -l "$path"
echo '=== ACTIVE HTTP SERVER NAMES ==='
sudo nginx -T 2>&1 | grep -E 'server_name (transport\.peluche-ebanache\.com|peluche-ebanache\.com)|conflicting server name' | head -25 || true
echo '=== DNS RESOLUTION ==='
getent ahostsv4 "$DOMAIN" | head -4 || true
echo '=== ORIGIN DIRECT HTTP (bypass Cloudflare) ==='
curl -sS --noproxy '*' -D /tmp/transport-dcv-origin-headers \
   -o /tmp/transport-dcv-origin-body --max-time 15 \
   --resolve "$DOMAIN:80:127.0.0.1" \
   -w 'ORIGIN status=%{http_code} ip=%{remote_ip} redirect=%{redirect_url}\n' \
   "http://$DOMAIN/.well-known/acme-challenge/$probe" || true
sed -n '1,14p' /tmp/transport-dcv-origin-headers
head -c 160 /tmp/transport-dcv-origin-body; echo
echo '=== PUBLIC HTTP VIA CLOUDFLARE (no redirect following) ==='
curl -sS --noproxy '*' -D /tmp/transport-dcv-public-headers \
   -o /tmp/transport-dcv-public-body --max-time 20 \
   -w 'PUBLIC status=%{http_code} ip=%{remote_ip} redirect=%{redirect_url}\n' \
   "http://$DOMAIN/.well-known/acme-challenge/$probe" || true
sed -n '1,24p' /tmp/transport-dcv-public-headers
head -c 160 /tmp/transport-dcv-public-body; echo
echo '=== PUBLIC WITH REDIRECTS (shows destination, if any) ==='
curl -sSL --noproxy '*' -D /tmp/transport-dcv-follow-headers \
   -o /tmp/transport-dcv-follow-body --max-redirs 4 --max-time 20 \
   -w 'FOLLOW status=%{http_code} ip=%{remote_ip} final=%{url_effective}\n' \
   "http://$DOMAIN/.well-known/acme-challenge/$probe" || true
grep -iE '^HTTP/|^location:|^server:' /tmp/transport-dcv-follow-headers || true
head -c 160 /tmp/transport-dcv-follow-body; echo
echo '=== END: no certificate request was made ==='
