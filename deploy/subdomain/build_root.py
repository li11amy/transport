#!/usr/bin/env python3
"""Prepare standalone PWA shell for transport.peluche-ebanache.com.

Read-only source + public timetable; writes only a dedicated staging directory.
Live JSON remains /srv/www/transport/transport_data.json, served by nginx alias.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from build_horarios import HTML
ASSETS=("icon-180.png","icon-192-rgb.png","icon-512-rgb.png","icon-512-maskable.png")


def shell(data, meta):
    safe=lambda value: json.dumps(value,ensure_ascii=False).replace("<","\\u003c")
    html=(HTML.replace("__TRANSPORT_DATA__",safe(data))
              .replace("__SERVICE_META__",safe(meta))
              .replace("__UPDATED__",""))
    # Keep the original path-based PWA unchanged. Only the dedicated root
    # build refers to root-scoped assets and root service worker.
    html=html.replace('/transport/', '/')
    if '/transport/' in html or 'id="officialAlerts"' not in html:
        raise ValueError("Unexpected transport template: do not publish")
    return html


def prepare(public_json, destination):
    payload=json.loads(Path(public_json).read_text(encoding="utf-8"))
    if not isinstance(payload.get("data"),dict) or len(payload["data"])!=6:
        raise ValueError("Expected all six transport city pairs")
    if not payload.get("meta",{}).get("checked_at"):
        raise ValueError("Missing timetable checked_at")
    destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    (destination/"index.html").write_text(shell(payload["data"],payload["meta"]),encoding="utf-8")

    manifest=json.loads((ROOT/"manifest.json").read_text(encoding="utf-8"))
    manifest.update({"id":"/","start_url":"/","scope":"/"})
    for icon in manifest["icons"]:
        if not icon["src"].startswith("/transport/"):
            raise ValueError("Unexpected icon path")
        icon["src"]=icon["src"].replace("/transport/","/",1)
    (destination/"manifest.json").write_text(
        json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")

    sw=(ROOT/"sw.js").read_text(encoding="utf-8")
    old='const CACHE="transport-bahia-v4", ROOT="/transport/";'
    if old not in sw:
        raise ValueError("Unrecognized transport service worker")
    sw=sw.replace(old,'const CACHE="transport-bahia-root-v1", ROOT="/";')
    (destination/"sw.js").write_text(sw,encoding="utf-8")

    for name in ASSETS:
        shutil.copyfile(ROOT/name,destination/name)
    print("Prepared root-scoped installable PWA:",destination)
    print("JSON remains shared with /transport/; no duplicate timetable updater")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--source-json",default="/srv/www/transport/transport_data.json")
    parser.add_argument("--destination",required=True)
    args=parser.parse_args()
    prepare(args.source_json,args.destination)
