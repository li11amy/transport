#!/usr/bin/env python3
"""Own only a temporary HTTP-01 vhost for transport.peluche-ebanache.com.

No existing AVÍO/Nginx host is edited. A marker prevents removing or
overwriting unrelated configurations. Run as root: setup | rollback.
"""
import os
import subprocess
import sys
from pathlib import Path

DOMAIN="transport.peluche-ebanache.com"
AVAILABLE=Path("/etc/nginx/sites-available/"+DOMAIN)
ENABLED=Path("/etc/nginx/sites-enabled/"+DOMAIN)
ROOT=Path("/srv/www/transport-pwa-root")
MARKER="# transport-acme-bootstrap-v1"

HTTP_VHOST=(MARKER+"\n"
    "server {\n"
    "    listen 80;\n"
    "    server_name "+DOMAIN+";\n"
    "    root "+str(ROOT)+";\n"
    "    location ^~ /.well-known/acme-challenge/ {\n"
    "        default_type text/plain;\n"
    "        try_files $uri =404;\n"
    "    }\n"
    "    location / { return 404; }\n"
    "}\n")

def run(*args):
    return subprocess.run(args,text=True,capture_output=True)

def owned():
    return (AVAILABLE.is_file() and
            AVAILABLE.read_text(encoding="utf-8").startswith(MARKER+"\n") and
            ENABLED.is_symlink() and ENABLED.resolve()==AVAILABLE)

def setup():
    if (AVAILABLE.exists() or ENABLED.exists() or ENABLED.is_symlink()):
        if owned() and AVAILABLE.read_text(encoding="utf-8")==HTTP_VHOST:
            print("Existing transport HTTP-01 bootstrap vhost reused")
            return
        raise RuntimeError("Transport vhost already exists, will not overwrite")
    if not (ROOT/"index.html").is_file():
        raise RuntimeError("Root-scoped PWA is not staged in "+str(ROOT))
    try:
        AVAILABLE.write_text(HTTP_VHOST,encoding="utf-8")
        AVAILABLE.chmod(0o644)
        ENABLED.symlink_to(AVAILABLE)
        check=run("nginx","-t")
        if check.returncode:
            raise RuntimeError("Nginx syntax check: "+check.stderr)
        result=run("systemctl","reload","nginx")
        if result.returncode:
            raise RuntimeError("Nginx reload: "+result.stderr)
    except Exception:
        if owned():
            ENABLED.unlink(missing_ok=True)
            AVAILABLE.unlink(missing_ok=True)
            run("nginx","-t")
            run("systemctl","reload","nginx")
        raise
    print("Temporary HTTP-only ACME challenge route enabled; existing hosts unchanged")

def rollback():
    if not owned():
        print("No owned temporary vhost to remove (possibly already HTTPS)")
        return
    ENABLED.unlink()
    AVAILABLE.unlink()
    check=run("nginx","-t")
    if check.returncode:
        raise RuntimeError("Nginx check after bootstrap removal: "+check.stderr)
    result=run("systemctl","reload","nginx")
    if result.returncode:
        raise RuntimeError("Nginx reload after bootstrap removal: "+result.stderr)
    print("Temporary HTTP-only vhost removed")

if __name__=="__main__":
    if os.geteuid()!=0 or len(sys.argv)!=2 or sys.argv[1] not in ("setup","rollback"):
        sys.exit("Usage (root): bootstrap_http.py setup | rollback")
    try:
        (setup if sys.argv[1]=="setup" else rollback)()
    except Exception as exc:
        sys.exit("ACME bootstrap refused: "+str(exc))
