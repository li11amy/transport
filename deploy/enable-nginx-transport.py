#!/usr/bin/env python3
"""One-time, fail-closed Nginx /transport/ installation.

Must be run with sudo on the target VPS AFTER staging /srv/www/transport.
Only touches the HTTPS server block for peluche-ebanache.com, with rollback.
"""
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DOMAIN = "peluche-ebanache.com"
SITE = Path("/etc/nginx/sites-enabled/peluche-ebanache.com")
SNIPPET = Path("/etc/nginx/snippets/transport-locations.conf")
PUBLIC = Path("/srv/www/transport")
INCLUDE = "include /etc/nginx/snippets/transport-locations.conf;"


def fail(message):
    raise RuntimeError(message)


def server_blocks(source):
    """Find balanced server {} bodies; skip comments and quoted strings."""
    for found in re.finditer(r"(?m)^\s*server\s*\{", source):
        start = found.start()
        brace = source.find("{", found.start(), found.end())
        depth, quoted, comment, escape = 0, None, False, False
        for pos in range(brace, len(source)):
            char = source[pos]
            if comment:
                if char == "\n":
                    comment = False
                continue
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if quoted:
                if char == quoted:
                    quoted = None
                continue
            if char in ("'", '"'):
                quoted = char
                continue
            if char == "#":
                comment = True
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    yield start, pos + 1
                    break


def select_https_block(source):
    matches = []
    for start, end in server_blocks(source):
        block = source[start:end]
        names = re.findall(r"(?m)^\s*server_name\s+([^;]+);", block)
        all_names = " ".join(names).split()
        if DOMAIN not in all_names:
            continue
        if not (re.search(r"\blisten\s+(?:\S+:)?443(?:\s|;)", block)
                or re.search(r"(?m)^\s*ssl_certificate\s+", block)):
            continue
        matches.append((start, end, block))
    if len(matches) != 1:
        fail("Expected exactly one HTTPS server for {}; found {}. No edits made.".format(
            DOMAIN, len(matches)))
    return matches[0]


def main():
    if os.geteuid() != 0:
        fail("Run with sudo.")
    for name in ("index.html", "transport_data.json", "manifest.json", "sw.js"):
        if not (PUBLIC / name).is_file():
            fail("Missing staged file: " + str(PUBLIC / name))

    if not SITE.exists():
        fail("Expected active Nginx site is absent: " + str(SITE))
    target = SITE.resolve(strict=True)
    old = target.read_text(encoding="utf-8")
    start, end, block = select_https_block(old)
    if INCLUDE in block:
        print("Nginx transport include already present; no changes made.")
        return
    if re.search(r"\blocation\s+(?:=|~\*?|\\^~)?\s*/transport(?:/|\s|$)", block):
        fail("Nginx already contains a /transport location. Inspect it manually.")

    snippet_src = Path(__file__).with_name("nginx-transport-location.conf")
    snippet_content = snippet_src.read_text(encoding="utf-8")
    if "location ^~ /transport/" not in snippet_content:
        fail("Unexpected snippet content.")
    if SNIPPET.exists():
        if SNIPPET.read_text(encoding="utf-8") != snippet_content:
            fail("Existing transport snippet differs; refusing overwrite.")
    else:
        SNIPPET.parent.mkdir(parents=True, exist_ok=True)
        SNIPPET.write_text(snippet_content, encoding="utf-8")
        SNIPPET.chmod(0o644)

    backup = target.with_name(target.name + ".transport-backup-" +
                              datetime.now().strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(target, backup)
    updated = old[:end - 1] + "\n    " + INCLUDE + "\n" + old[end - 1:]
    temp = target.with_name(target.name + ".transport-tmp")
    try:
        temp.write_text(updated, encoding="utf-8")
        shutil.copymode(target, temp)
        os.replace(temp, target)
        subprocess.run(["nginx", "-t"], check=True)
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
    except Exception:
        shutil.copy2(backup, target)
        subprocess.run(["nginx", "-t"], check=False)
        subprocess.run(["systemctl", "reload", "nginx"], check=False)
        raise
    finally:
        temp.unlink(missing_ok=True)
    print("Installed /transport/ into {}. Backup: {}".format(target, backup))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("FAILED: {}".format(exc), file=sys.stderr)
        sys.exit(1)
