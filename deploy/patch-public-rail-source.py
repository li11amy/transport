#!/usr/bin/env python3
"""Patch only user-visible Renfe source links in published static HTML shells.

The 15-minute updater already publishes JSON independently. HTML does not
rebuild during those runs. Use this once during an approved source deploy.
"""
import argparse
import os
import tempfile
from pathlib import Path

START = '      if(t.fuente_cambio) {'
END = '      extra.appendChild(details);'


def source_block(html):
    start = html.index(START)
    end = html.index(END, start)
    return html[start:end]


def patch_html(current, template):
    new = source_block(template)
    if 'technicalRenfe' not in new or 'tiempo-real.renfe.com' not in new:
        raise ValueError("New passenger-facing source block is missing")
    old = source_block(current)
    if old == new:
        return current
    if ('source.href=t.fuente_cambio;' not in old or
            'technicalRenfe' in old or 'Fuente' not in old):
        raise ValueError("Published HTML differs from the expected old source block")
    return current.replace(old, new, 1)


def patch_file(path, template, write=False):
    path = Path(path)
    current = path.read_text(encoding="utf-8")
    updated = patch_html(current, template)
    if current == updated:
        return False
    if write:
        fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(updated)
            os.chmod(temporary, 0o644)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return True


def main():
    # Running `python3 deploy/patch-public-rail-source.py` puts only deploy/
    # on sys.path. Resolve the repository root for direct script execution.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from build_horarios import HTML
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually change public shells")
    opts = parser.parse_args()
    paths = [Path("/srv/www/transport/index.html"),
             Path("/srv/www/transport-pwa-root/index.html")]
    # Validate both targets before changing even one.
    changes = [patch_file(p, HTML, write=False) for p in paths]
    print("Public HTML validated:", [(str(p), changed) for p, changed in zip(paths, changes)])
    if opts.apply:
        for path, changed in zip(paths, changes):
            if changed:
                patch_file(path, HTML, write=True)
                print("Updated passenger source link:", path)


if __name__ == "__main__":
    main()
