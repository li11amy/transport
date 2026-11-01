#!/usr/bin/env python3
"""Idempotent surgical HTML enhancement: exact GTFS train -> private Telegram.

Source HTML builder is patched separately in the feature branch. This script
updates only the two installed shells once the PR tests and guarded deployment
are complete, never the timetable JSON or other domains.
"""
import argparse
import os
from pathlib import Path

ROOT = Path("/srv/www/transport-pwa-root/index.html")
LEGACY = Path("/srv/www/transport/index.html")
BOT_NAME = "Alarma_cmtbc_bot"

BASE = '    const marked=Boolean(status||t.aviso);\n'
EXT = '''    const marked=Boolean(status||t.aviso);
    const trainCheck=checkableTrain(t, fromCity+"-"+toCity);
'''
BEFORE_FLAGS = '  const fragment=document.createDocumentFragment();\n'
AFTER_FLAGS = '''  const fragment=document.createDocumentFragment();
'''
SOURCE_ANCHOR = 'function update() {\n'
SOURCE_REPLACEMENT = '''function checkableTrain(t, route) {
  if(t.tipo!=="tren"||!["C-1","MD"].includes(t.linea)||!t.trip_id||
     t.fecha_servicio!==spanishToday()||day!==todayGroup()) return "";
  const routeCodes={"puerto-cadiz":"pc","puerto-jerez":"pj",
    "cadiz-puerto":"cp","cadiz-jerez":"cj",
    "jerez-puerto":"jp","jerez-cadiz":"jc"};
  const code=routeCodes[route];
  const date=t.fecha_servicio.replaceAll("-","");
  const departure=(t.salida||"").replace(":","");
  const line=t.linea==="C-1"?"C1":"MD";
  const token="r_"+date+"_"+code+"_"+line+"_"+t.trip_id+"_"+departure;
  return code&&/^[A-Za-z0-9_-]{1,64}$/.test(token) ? token : "";
}
function update() {
'''
LINK_ANCHOR = '      details.appendChild(message);\n'
LINK_REPLACEMENT = '''      details.appendChild(message);
      if(trainCheck){
        const link=document.createElement("a");
        link.className="trip-check-link";
        link.href="https://t.me/Alarma_cmtbc_bot?start="+trainCheck;
        link.target="_blank";
        link.rel="noopener noreferrer";
        link.textContent="↗ Comprobar ahora en Telegram";
        details.appendChild(link);
      }
'''
CSS_ANCHOR = '.trip-extra a{display:inline-block;margin-left:8px}\n'
CSS_REPLACEMENT = '''.trip-extra a{display:inline-block;margin-left:8px}
.trip-extra .trip-check-link{margin:9px 0 0;display:table;border:1px solid #9db8ee;
  background:#eef4ff;color:#1f4fa8;border-radius:9px;padding:7px 10px;
  text-decoration:none;font-size:12px;font-weight:600}
'''
# Even on white/no-alert trains the details expander should be accessible.
MODIFICATIONS = [
    (BASE, EXT),
    (SOURCE_ANCHOR, SOURCE_REPLACEMENT),
    ('    if(marked) {\n      const info=document.createElement("span");',
     '    if(marked||trainCheck) {\n      const info=document.createElement("span");'),
    ('    if(marked) {\n      const extra=document.createElement("tr");',
     '    if(marked||trainCheck) {\n      const extra=document.createElement("tr");'),
    (LINK_ANCHOR, LINK_REPLACEMENT),
    ('      tr.setAttribute("aria-label",t.linea+": "+(cancelled?"cancelado":"cambios o aviso")+". Ver detalles");',
     '      tr.setAttribute("aria-label",t.linea+": "+(cancelled?"cancelado":marked?"cambios o aviso":"consultar estado")+". Ver detalles");'),
    (CSS_ANCHOR, CSS_REPLACEMENT),
]


def patch(source):
    if 'function checkableTrain(t, route) {' in source:
        if '↗ Comprobar ahora en Telegram' not in source:
            raise ValueError("Partially patched HTML found")
        return source
    for original, replacement in MODIFICATIONS:
        if source.count(original) != 1:
            raise ValueError("Unexpected HTML shell marker: {!r} count={}".format(
                original[:65], source.count(original)))
        source = source.replace(original, replacement, 1)
    return source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Atomically patch the two verified public HTML shells")
    args = parser.parse_args()
    changes = []
    for path in (ROOT, LEGACY):
        if not path.is_file():
            raise SystemExit("Missing known live shell: {}".format(path))
        original = path.read_text(encoding="utf-8")
        if '<title>Horarios de transporte' not in original:
            raise SystemExit("Unrecognized transport shell: {}".format(path))
        revised = patch(original)
        changes.append((path, original, revised))
    if not args.apply:
        for path, before, after in changes:
            print("{}: {}".format(path, "already patched" if before == after else "ready to patch"))
        return
    for path, before, after in changes:
        if before == after:
            continue
        temp = path.with_suffix(".html.tmp")
        temp.write_text(after, encoding="utf-8")
        os.chmod(temp, path.stat().st_mode & 0o777)
        os.replace(temp, path)
        print("Patched: {}".format(path))


if __name__ == "__main__":
    main()
