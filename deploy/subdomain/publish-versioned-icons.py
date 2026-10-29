#!/usr/bin/env python3
"""Refresh Android launcher artwork with new manifest icon URLs (Chrome 144+).

Only root PWA assets are touched; the old /transport/ page, data, timer,
Nginx, AVÍO and certificate are not touched. Requires only Python stdlib.
"""
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

SOURCE=Path("/home/ubuntu/Sites/transport")
PUBLIC=Path("/srv/www/transport-pwa-root")
ICON_MAP={
    "icon-192-rgb.png":"icon-192-rgb-v2.png",
    "icon-512-rgb.png":"icon-512-rgb-v2.png",
    "icon-512-maskable.png":"icon-512-maskable-large-v2.png",
}
ASSET_SOURCES={
    "icon-192-rgb-v2.png":"icon-192-rgb.png",
    "icon-512-rgb-v2.png":"icon-512-rgb.png",
    "icon-512-maskable-large-v2.png":"icon-512-rgb.png",
}
CORE=("manifest.json","index.html","sw.js")


def png(source, dimension):
    data=source.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("Invalid PNG: "+str(source))
    w,h=struct.unpack(">II",data[16:24])
    if (w,h,data[25])!=(dimension,dimension,2):
        raise RuntimeError("Expected truecolor RGB {}: {}".format(dimension,source))
    return data


def atomic(path, content):
    fd,temp=tempfile.mkstemp(prefix="."+path.name+".",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as handle:
            handle.write(content)
        os.chmod(temp,0o644)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def prepare(manifest_data, html, worker):
    manifest=json.loads(manifest_data.decode("utf-8"))
    if manifest.get("id")!="/" or manifest.get("scope")!="/" or manifest.get("start_url")!="/":
        raise RuntimeError("Not the root-scoped transport PWA")
    changed=set()
    for item in manifest.get("icons",[]):
        source=item.get("src","").removeprefix("/")
        if source in ICON_MAP:
            item["src"]="/"+ICON_MAP[source]
            changed.add(source)
        elif source in ICON_MAP.values():
            changed.add(next(k for k,v in ICON_MAP.items() if v==source))
        else:
            raise RuntimeError("Unexpected manifest icon: "+source)
    if changed!=set(ICON_MAP):
        raise RuntimeError("Missing launcher icon purpose in live manifest")

    if not re.search(r'manifest.json\?v=(2|3|4)"',html):
        raise RuntimeError("Unexpected live manifest link; inspect manually")
    html=re.sub(r'manifest.json\?v=(2|3|4)"','manifest.json?v=4"',html)

    if 'transport-bahia-root-v3' not in worker:
        if 'transport-bahia-root-v2' in worker:
            worker=worker.replace('transport-bahia-root-v2','transport-bahia-root-v3')
        elif 'transport-bahia-root-v1' in worker:
            worker=worker.replace('transport-bahia-root-v1','transport-bahia-root-v3')
        else:
            raise RuntimeError("Unexpected root SW cache; inspect manually")
    for filename in ICON_MAP.values():
        expr='ROOT+"'+filename+'"'
        if expr not in worker:
            if 'ROOT+"icon-512-maskable.png"' not in worker:
                raise RuntimeError("Root SW asset anchor missing")
            worker=worker.replace('ROOT+"icon-512-maskable.png"',
                                  'ROOT+"icon-512-maskable.png",'+expr)
    if 'ROOT="/"' not in worker:
        raise RuntimeError("Unexpected service worker scope")

    return (json.dumps(manifest,ensure_ascii=False,indent=2)+"\n").encode("utf-8"),html.encode("utf-8"),worker.encode("utf-8")


def main():
    if os.uname().nodename!="vps-cd9917e0":
        raise RuntimeError("Wrong host")
    os.chdir(SOURCE)
    print("HOST:",os.uname().nodename,"DIR:",os.getcwd(),flush=True)
    if subprocess.check_output(["git","branch","--show-current"],text=True).strip()!="main":
        raise RuntimeError("Expected main source checkout")
    git_status=subprocess.check_output(["git","status","--porcelain"],text=True).strip()
    print("Git status:",git_status or "clean")
    if git_status:
        raise RuntimeError("Source checkout has local edits")
    for name in CORE:
        if not (PUBLIC/name).is_file():
            raise RuntimeError("Missing published PWA: "+name)

    generated={}
    for filename,source in ASSET_SOURCES.items():
        dimension=192 if filename.startswith("icon-192") else 512
        generated[filename]=png(SOURCE/source,dimension)

    originals={name:(PUBLIC/name).read_bytes() for name in CORE}
    new_manifest,new_html,new_sw=prepare(
        originals["manifest.json"],originals["index.html"].decode("utf-8"),
        originals["sw.js"].decode("utf-8"))
    replacements={**generated,
                  "manifest.json":new_manifest,"index.html":new_html,
                  "sw.js":new_sw}
    previous={name:(PUBLIC/name).read_bytes() if (PUBLIC/name).is_file() else None
              for name in replacements}
    applied=[]
    try:
        # Assets must be present before publishing the manifest or SW.
        for name in list(generated)+list(CORE):
            if previous[name]==replacements[name]:
                continue
            atomic(PUBLIC/name,replacements[name])
            applied.append(name)
        manifest=json.loads((PUBLIC/"manifest.json").read_text(encoding="utf-8"))
        for item in manifest["icons"]:
            assert (PUBLIC/item["src"].lstrip("/")).is_file()
        assert 'manifest.json?v=4' in (PUBLIC/"index.html").read_text(encoding="utf-8")
        assert 'transport-bahia-root-v3' in (PUBLIC/"sw.js").read_text(encoding="utf-8")
    except Exception:
        for name in reversed(applied):
            if previous[name] is None:
                (PUBLIC/name).unlink(missing_ok=True)
            else:
                atomic(PUBLIC/name,previous[name])
        raise
    print("Updated:",", ".join(applied) if applied else "already at v4")
    print("Manifest references new icon URLs; Android now can detect a launcher icon change.")
    print("Existing data, services, TLS, Git main and original /transport/ unaffected.")
    print("For immediate visual test: remove the old home icon/app and reinstall from Chrome.")


if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        print("PWA ICON NOT UPDATED:",exc,file=sys.stderr)
        sys.exit(1)
