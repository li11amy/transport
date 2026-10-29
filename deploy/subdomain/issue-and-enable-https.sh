#!/usr/bin/env bash
# Obtain a SEPARATE Let's Encrypt certificate for the transport hostname.
# No downtime, no changes to the main peluche/AVÍO certificate or containers.
set -euo pipefail

REPO="/home/ubuntu/Sites/transport"
ROOT="/srv/www/transport-pwa-root"
DOMAIN="transport.peluche-ebanache.com"
BRANCH="feature/transport-root-subdomain-20261029"
cd "$REPO"
echo "HOST=$(hostname) DIR=$PWD"
git status --short
test "$(hostname)" = "vps-cd9917e0" || { echo "Wrong VPS"; exit 1; }
test "$(git branch --show-current)" = "main" || { echo "Expected main checkout"; exit 1; }
test -z "$(git status --porcelain)" || { echo "Inspect local Git edits before proceeding"; exit 1; }
test -s "$ROOT/index.html" && test -s "$ROOT/manifest.json" ||
  { echo "Root PWA is not staged; stop without changing Nginx"; exit 1; }
test -s /srv/www/transport/transport_data.json ||
  { echo "Missing shared timetable JSON; stop"; exit 1; }
for command in certbot nginx openssl curl; do
    command -v "$command" >/dev/null || { echo "Missing $command"; exit 1; }
done

git fetch origin "$BRANCH"
BOOTSTRAP="deploy/subdomain/bootstrap_http.py"
ACTIVATE="deploy/subdomain/enable_https.py"
cert="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"

# A previous interrupted run may already have issued the correct certificate.
# Activate it without a second ACME request or rate-limit risk.
if sudo test -s "$cert" &&
   sudo openssl x509 -in "$cert" -noout -checkhost "$DOMAIN" 2>/dev/null |
      grep -q "does match" &&
   sudo openssl x509 -in "$cert" -noout -checkend 86400 >/dev/null 2>&1; then
    echo "Existing dedicated TLS certificate is valid; skipping issuance."
    git show "FETCH_HEAD:$ACTIVATE" | sudo python3 -
    curl -fsSI --max-time 20 "https://$DOMAIN/"
    curl -fsSI --max-time 20 "https://$DOMAIN/transport_data.json"
    exit 0
fi
git show "FETCH_HEAD:$BOOTSTRAP" | sudo python3 - setup

challenge=""
complete=0
cleanup() {
    if [ -n "$challenge" ]; then rm -f "$challenge" || true; fi
    if [ "$complete" -ne 1 ]; then
        git show "FETCH_HEAD:$BOOTSTRAP" | sudo python3 - rollback ||
            echo "Review temporary Nginx HTTP-01 vhost manually"
    fi
}
trap cleanup EXIT

mkdir -p "$ROOT/.well-known/acme-challenge"
probe="avio-acme-check-$(date +%s)-$$"
challenge="$ROOT/.well-known/acme-challenge/$probe"
printf 'avio-acme-ready-%s\n' "$probe" > "$challenge"
chmod 644 "$challenge"
expected="$(cat "$challenge")"

# Test both origin Nginx and Cloudflare's public HTTP route BEFORE issuing
# a certificate. A Cloudflare redirect or WAF challenge may prevent HTTP-01.
origin="$(curl -fsS --max-time 12 --resolve "$DOMAIN:80:127.0.0.1" \
  "http://$DOMAIN/.well-known/acme-challenge/$probe")"
test "$origin" = "$expected" ||
  { echo "Origin HTTP-01 probe differs; nothing issued"; exit 1; }
public="$(curl -fsSL --max-redirs 3 --max-time 25 \
  "http://$DOMAIN/.well-known/acme-challenge/$probe")"
test "$public" = "$expected" || {
    echo "Cloudflare HTTP-01 probe not reachable; check HTTPS redirects/WAF"
    exit 1
}
echo "HTTP-01 challenge reachable on both origin and public transport hostname."

# Certbot uses its existing ACME account, or asks for registration details.
# A dedicated certificate avoids modifying the main-domain lineage.
reload_cmd="$(command -v systemctl) reload nginx"
sudo certbot certonly --webroot \
    --webroot-path "$ROOT" \
    --cert-name "$DOMAIN" \
    -d "$DOMAIN" \
    --agree-tos \
    --deploy-hook "$reload_cmd"

cert="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
sudo test -s "$cert" || { echo "Certbot did not create dedicated certificate"; exit 1; }
sudo openssl x509 -in "$cert" -noout -checkhost "$DOMAIN"
sudo openssl x509 -in "$cert" -noout -checkend 86400

# Replace ONLY our marked temporary HTTP vhost with final HTTP+HTTPS vhosts.
git show "FETCH_HEAD:$ACTIVATE" | sudo python3 -
complete=1
trap - EXIT
rm -f "$challenge"
echo "Checking public URLs:"
curl -fsSI --max-time 20 "https://$DOMAIN/"
curl -fsSI --max-time 20 "https://$DOMAIN/transport_data.json"
echo "Transport subdomain enabled with its own renewing Let's Encrypt certificate."
echo "Existing https://peluche-ebanache.com/transport/ remains unchanged."
