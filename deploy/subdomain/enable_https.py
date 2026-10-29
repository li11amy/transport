#!/usr/bin/env python3
"""Guarded HTTPS vhost for transport.peluche-ebanache.com.

Require explicit DNS and a certificate covering the subdomain. An owned
temporary HTTP-01 challenge vhost may be replaced after issuance. Never
change the existing AVÍO host or any unrelated Nginx configuration.
"""
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

DOMAIN="transport.peluche-ebanache.com"
ORIGINAL=Path("/etc/nginx/sites-available/peluche-ebanache.com")
AVAILABLE=Path("/etc/nginx/sites-available/"+DOMAIN)
ENABLED=Path("/etc/nginx/sites-enabled/"+DOMAIN)
ROOT=Path("/srv/www/transport-pwa-root")
OWNED_BOOTSTRAP="# transport-acme-bootstrap-v1"
PREFERRED_CERT=Path("/etc/letsencrypt/live/"+DOMAIN+"/fullchain.pem")
PREFERRED_KEY=Path("/etc/letsencrypt/live/"+DOMAIN+"/privkey.pem")


def run(*args):
    return subprocess.run(args,text=True,capture_output=True)


def install():
    if os.geteuid()!=0:
        raise RuntimeError("Run as root with sudo")
    required=("index.html","manifest.json","sw.js","icon-192-rgb.png",
              "icon-512-rgb.png","icon-512-maskable.png")
    for filename in required:
        if not (ROOT/filename).is_file():
            raise RuntimeError("Missing root PWA asset: "+filename)
    if not Path("/srv/www/transport/transport_data.json").is_file():
        raise RuntimeError("Original live timetable JSON missing")
    bootstrap = (AVAILABLE.is_file() and
                 AVAILABLE.read_text(encoding="utf-8").startswith(OWNED_BOOTSTRAP+"\n") and
                 ENABLED.is_symlink() and ENABLED.resolve()==AVAILABLE)
    if (AVAILABLE.exists() or ENABLED.exists() or ENABLED.is_symlink()) and not bootstrap:
        raise RuntimeError("Existing non-bootstrap subdomain Nginx configuration: inspect manually")
    try:
        addresses=socket.getaddrinfo(DOMAIN,443)
        if not addresses:
            raise OSError("empty DNS")
    except OSError as exc:
        raise RuntimeError(
            "DNS missing. Create a proxied Cloudflare CNAME: transport -> "
            "peluche-ebanache.com. No Nginx changes made.") from exc

    if not ORIGINAL.exists():
        raise RuntimeError("Existing main-domain Nginx config absent: "+str(ORIGINAL))
    if PREFERRED_CERT.is_file() and PREFERRED_KEY.is_file():
        cert, key = str(PREFERRED_CERT), str(PREFERRED_KEY)
    else:
        # The old main-domain certificate is used only if it ALREADY covers
        # this hostname. It is never enlarged or overwritten.
        original=ORIGINAL.read_text(encoding="utf-8")
        certificates=set(re.findall(r"(?m)^\s*ssl_certificate\s+([^;\s]+)\s*;",original))
        keys=set(re.findall(r"(?m)^\s*ssl_certificate_key\s+([^;\s]+)\s*;",original))
        if len(certificates)!=1 or len(keys)!=1:
            raise RuntimeError("Cannot identify the existing main-domain certificate")
        cert, key = next(iter(certificates)), next(iter(keys))
    if not Path(cert).is_file() or not Path(key).is_file():
        raise RuntimeError("Selected TLS certificate/key inaccessible")
    check=run("openssl","x509","-in",cert,"-noout","-checkhost",DOMAIN)
    if check.returncode!=0 or "does NOT match" in check.stdout:
        raise RuntimeError(
            "Existing TLS certificate DOES NOT cover "+DOMAIN+". "
            "Obtain an origin certificate or Let's Encrypt certificate for this "
            "hostname first. No Nginx changes made.\n"
            "Current certificate: "+cert+"\n"+check.stdout+check.stderr)

    text = (
        "server {\n"
        "    listen 80;\n"
        "    server_name "+DOMAIN+";\n"
        "    root "+str(ROOT)+";\n"
        "    location ^~ /.well-known/acme-challenge/ {\n"
        "        default_type text/plain;\n"
        "        try_files $uri =404;\n"
        "    }\n"
        "    location / { return 308 https://$host$request_uri; }\n"
        "}\n\n"
        "server {\n"
        "    listen 443 ssl;\n"
        "    server_name "+DOMAIN+";\n"
        "    ssl_certificate "+cert+";\n"
        "    ssl_certificate_key "+key+";\n"
        "    root "+str(ROOT)+";\n"
        "    index index.html;\n"
        "    location ^~ /.well-known/acme-challenge/ {\n"
        "        default_type text/plain;\n"
        "        try_files $uri =404;\n"
        "    }\n"
        "    location = /transport_data.json {\n"
        "        alias /srv/www/transport/transport_data.json;\n"
        '        add_header Cache-Control "no-store, max-age=0" always;\n'
        "    }\n"
        "    location / {\n"
        "        try_files $uri $uri/ /index.html;\n"
        '        add_header Cache-Control "no-cache, must-revalidate" always;\n'
        "    }\n"
        "}\n"
    )
    previous=AVAILABLE.read_text(encoding="utf-8") if bootstrap else None
    temp=AVAILABLE.with_suffix(".new")
    if temp.exists():
        raise RuntimeError("Unexpected temporary Nginx file: "+str(temp))
    try:
        temp.write_text(text,encoding="utf-8")
        temp.chmod(0o644)
        os.replace(temp, AVAILABLE)
        if not bootstrap:
            ENABLED.symlink_to(AVAILABLE)
        test=run("nginx","-t")
        if test.returncode!=0:
            raise RuntimeError("nginx -t rejected configuration: "+test.stderr)
        reload=run("systemctl","reload","nginx")
        if reload.returncode!=0:
            raise RuntimeError("Nginx reload failed: "+reload.stderr)
    except Exception:
        temp.unlink(missing_ok=True)
        if previous is not None:
            AVAILABLE.write_text(previous, encoding="utf-8")
        else:
            ENABLED.unlink(missing_ok=True)
            AVAILABLE.unlink(missing_ok=True)
        run("nginx","-t")
        run("systemctl","reload","nginx")
        raise
    print("HTTPS subdomain enabled: https://"+DOMAIN+"/")
    print("Timetable JSON is shared with https://peluche-ebanache.com/transport/")


if __name__=="__main__":
    try:
        install()
    except Exception as exc:
        print("NOT ACTIVATED:",str(exc),file=sys.stderr)
        sys.exit(1)
