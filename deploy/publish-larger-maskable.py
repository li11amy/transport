#!/usr/bin/env python3
"""Make Android launcher art larger using the existing truecolor icon.

No image regeneration, server restart, Git pull or timetable rebuild.
Only public root-PWA icon, service-worker cache version and manifest-link
query are updated. The old smaller maskable remains in Git history.
"""
import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

SOURCE = Path("/home/ubuntu/Sites/transport")
PUBLIC = Path("/srv/www/transport-pwa-root")
EXPECTED_HOST = "vps-cd9917e0"
FILES = ("icon-512-maskable.png", "sw.js", "index.html")


def new_contents(icon, manifest, worker, html):
    """Validate PWA structure before modifying any published asset."""
    if icon[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Normal launcher asset is not PNG")
    width, height = struct.unpack(">II", icon[16:24])
    if (width, height, icon[25]) != (512, 512, 2):
        raise ValueError("Expected 512x512 RGB PNG")
    if not any(item.get("src") == "/icon-512-rgb.png"
               and "any" in item.get("purpose", "").split()
               for item in manifest.get("icons", [])):
        raise ValueError("Existing PWA does not use expected full-size icon")
    if not any(item.get("src") == "/icon-512-maskable.png"
               and "maskable" in item.get("purpose", "").split()
               for item in manifest.get("icons", [])):
        raise ValueError("Existing manifest does not have maskable image")
    if "transport-bahia-root-v2" in worker and 'manifest.json?v=3' in html:
        return None
    if "transport-bahia-root-v1" not in worker:
        raise ValueError("Unexpected root service-worker version")
    if 'manifest.json?v=2' not in html:
        raise ValueError("Unexpected root manifest link")
    return {
        "icon-512-maskable.png": icon,
        "sw.js": worker.replace(
            "transport-bahia-root-v1", "transport-bahia-root-v2").encode("utf-8"),
        "index.html": html.replace(
            "manifest.json?v=2", "manifest.json?v=3").encode("utf-8"),
    }


def atomic_replace(path, data):
    handle, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    if os.uname().nodename != EXPECTED_HOST:
        raise RuntimeError("Unexpected host; refusing deployment")
    os.chdir(SOURCE)
    print("HOST:", os.uname().nodename, "DIR:", os.getcwd(), flush=True)
    if subprocess.check_output(["git", "branch", "--show-current"], text=True).strip() != "main":
        raise RuntimeError("Expected main checkout")
    status = subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
    print("Git status:", status or "clean")
    if status:
        raise RuntimeError("Local source changes require inspection")
    for name in FILES:
        if not (PUBLIC / name).is_file():
            raise RuntimeError("Missing production PWA file: " + name)
    icon = (SOURCE / "icon-512-rgb.png").read_bytes()
    maskable = (PUBLIC / "icon-512-maskable.png").read_bytes()
    manifest = json.loads((PUBLIC / "manifest.json").read_text(encoding="utf-8"))
    worker = (PUBLIC / "sw.js").read_text(encoding="utf-8")
    html = (PUBLIC / "index.html").read_text(encoding="utf-8")
    replacements = new_contents(icon, manifest, worker, html)
    if replacements is None:
        if maskable != icon:
            raise RuntimeError("PWA already updated but maskable icon differs")
        print("Already installed; no changes needed")
        return
    originals = {name: (PUBLIC / name).read_bytes() for name in FILES}
    changed = []
    try:
        for name in FILES:
            atomic_replace(PUBLIC / name, replacements[name])
            changed.append(name)
    except Exception:
        for name in reversed(changed):
            atomic_replace(PUBLIC / name, originals[name])
        raise
    print("Updated:", ", ".join(changed))
    print("Android icon now uses larger normal route logo within adaptive circle")
    print("Root manifest version: v3; root service worker cache: v2")
    print("Bus/train/boat data, TLS, Nginx, timer, old /transport/ untouched")
    print("Reinstall PWA on Android to refresh launcher icon, if previously installed")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ICON NOT DEPLOYED:", exc, file=sys.stderr)
        sys.exit(1)
