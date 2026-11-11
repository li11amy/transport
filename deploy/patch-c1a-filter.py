#!/usr/bin/env python3
"""Safely patch only C-1a row filtering and Renfe strike-banner visibility.

Do not regenerate the production PWA from GitHub Pages HTML: both published
shells have their own service-worker/install details and dynamic JSON.
"""
import argparse
import os
import shutil
import socket
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_SHELLS = (
    Path("/srv/www/transport/index.html"),
    Path("/srv/www/transport-pwa-root/index.html"),
)
FILTER_START = '  const routeTrips=DATA[key]||[];\n'
FILTER_END = '  trips.sort((a,b)=>{\n'
OLD_FILTER = (
    '  const routeTrips=DATA[key]||[];\n'
    '  const trips=routeTrips.filter(t=>types.has(t.tipo)&&operates(t.dias));\n'
)
OLD_ALERT = (
    '  const activeAlerts=day===todayGroup()\n'
    '    ? (SERVICE_META.official_alerts||[]).filter(a=>a.date===spanishToday())\n'
    '    : [];\n'
)
NEW_ALERT = (
    '  const activeAlerts=types.has("tren")&&day===todayGroup()\n'
    '    ? (SERVICE_META.official_alerts||[]).filter(a=>a.date===spanishToday())\n'
    '    : [];\n'
)


def filter_block(html):
    start = html.index(FILTER_START)
    end = html.index(FILTER_END, start)
    return html[start:end]


def patch_html(published, template):
    new = filter_block(template)
    if ('const officialC1=' not in new
            or 'closeClock(o.salida,t.salida)' not in new):
        raise ValueError("Template C-1a filter missing")
    old = filter_block(published)
    if old == OLD_FILTER:
        published = published.replace(old, new, 1)
    elif old != new:
        raise ValueError("Unknown published filter; refusing patch")

    if NEW_ALERT in published:
        return published
    if published.count(OLD_ALERT) != 1:
        raise ValueError("Unknown published Renfe banner block; refusing patch")
    return published.replace(OLD_ALERT, NEW_ALERT, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    import sys
    sys.path.insert(0, str(ROOT))
    from build_horarios import HTML
    if args.apply:
        if socket.gethostname() != "vps-cd9917e0":
            raise RuntimeError("Wrong host")
        if subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT,
            text=True, capture_output=True, check=True,
        ).stdout.strip():
            raise RuntimeError("Dirty source checkout; refusing patch")
    prepared = []
    for path in PUBLIC_SHELLS:
        before = path.read_text(encoding="utf-8")
        after = patch_html(before, HTML)
        prepared.append((path, before, after))
        print(path, "needs update:", before != after)
    if not args.apply:
        return

    backup = Path("/home/ubuntu/Backups/Transport") / (
        "before-c1a-classification-" + datetime.now(
            ZoneInfo("Europe/Madrid")).strftime("%Y%m%d-%H%M%S"))
    changed = [(p, before, after) for p, before, after in prepared
               if before != after]
    if changed:
        backup.mkdir(parents=True, exist_ok=False)
    for path, before, after in changed:
        shutil.copy2(path, backup / (
            "transport-index.html" if path == PUBLIC_SHELLS[0]
            else "transport-root-index.html"))
        fd, temp = tempfile.mkstemp(prefix=".index.c1a.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(after)
            os.chmod(temp, 0o644)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        print("Patched:", path)
    print("Backup:", backup if changed else "not needed")


if __name__ == "__main__":
    main()
