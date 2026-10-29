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
# The manifest MUST change icon URL strings, not only image bytes.
# Chrome 144+ considers unchanged icon URLs unchanged and can retain an old WebAPK.
ROOT_ICON_NAMES={
    "icon-192-rgb.png": "icon-192-rgb-v2.png",
    "icon-512-rgb.png": "icon-512-rgb-v2.png",
    "icon-512-maskable.png": "icon-512-maskable-large-v2.png",
}


def shell(data, meta):
    safe=lambda value: json.dumps(value,ensure_ascii=False).replace("<","\\u003c")
    html=(HTML.replace("__TRANSPORT_DATA__",safe(data))
              .replace("__SERVICE_META__",safe(meta))
              .replace("__UPDATED__",""))
    # Keep the original path-based PWA unchanged. Only the dedicated root
    # build refers to root-scoped assets and root service worker.
    html=html.replace('/transport/', '/')
    # Prevent installed Android launchers from retaining old, smaller art.
    html=html.replace('manifest.json?v=2', 'manifest.json?v=4')
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
        filename=icon["src"].rsplit("/",1)[-1]
        if filename not in ROOT_ICON_NAMES:
            raise ValueError("Unexpected icon asset: "+filename)
        icon["src"]="/"+ROOT_ICON_NAMES[filename]
    (destination/"manifest.json").write_text(
        json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")

    sw=(ROOT/"sw.js").read_text(encoding="utf-8")
    old='const CACHE="transport-bahia-v4", ROOT="/transport/";'
    if old not in sw:
        raise ValueError("Unrecognized transport service worker")
    sw=sw.replace(old,'const CACHE="transport-bahia-root-v3", ROOT="/";')
    if 'ROOT+"icon-512-maskable.png"' not in sw:
        raise ValueError("Service worker assets format changed")
    sw=sw.replace('ROOT+"icon-512-maskable.png"',
                  'ROOT+"icon-512-maskable.png",'+
                  'ROOT+"icon-192-rgb-v2.png",'+
                  'ROOT+"icon-512-rgb-v2.png",'+
                  'ROOT+"icon-512-maskable-large-v2.png"')
    (destination/"sw.js").write_text(sw,encoding="utf-8")

    for name in ASSETS:
        # Keep the earlier root filenames for existing installed browsers.
        original = "icon-512-rgb.png" if name == "icon-512-maskable.png" else name
        shutil.copyfile(ROOT/original, destination/name)
    for original, versioned in ROOT_ICON_NAMES.items():
        # The exact existing blue-and-yellow route artwork, not a redraw.
        source = "icon-512-rgb.png" if original=="icon-512-maskable.png" else original
        shutil.copyfile(ROOT/source, destination/versioned)
    print("Prepared root-scoped installable PWA:",destination)
    print("JSON remains shared with /transport/; no duplicate timetable updater")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--source-json",default="/srv/www/transport/transport_data.json")
    parser.add_argument("--destination",required=True)
    args=parser.parse_args()
    prepare(args.source_json,args.destination)
