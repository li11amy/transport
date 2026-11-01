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
LINK_REPLACEMENT = '''      const main=document.createElement("div");
      main.className="trip-extra-main";
      main.appendChild(message);
      if(trainCheck){
        const link=document.createElement("a");
        link.className="trip-check-link";
        link.href="https://t.me/Alarma_cmtbc_bot?start="+trainCheck;
        link.target="_blank";
        link.rel="noopener noreferrer";
        link.setAttribute("aria-label","Comprobar tren en Telegram");
        link.title="Comprobar tren en Telegram";
        link.innerHTML='<svg data-icon="message-circle" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/></svg>';
        main.appendChild(link);
      }
      details.appendChild(main);
'''
CSS_ANCHOR = '.trip-extra a{display:inline-block;margin-left:8px}\n'
CSS_REPLACEMENT = '''.trip-extra a{display:inline-block;margin-left:8px}
.trip-extra-main{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.trip-extra-main > span{flex:1;min-width:0}
.trip-extra .trip-check-link{margin:0;display:inline-flex;align-items:center;justify-content:center;
  flex:none;width:36px;height:36px;padding:0;color:#6b7280;text-decoration:none}
.trip-extra .trip-check-link svg{display:block;width:18px;height:18px;fill:none;
  stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.trip-extra .trip-check-link:hover{color:#1f4fa8}
.trip-extra .trip-check-link:focus-visible{outline:2px solid #1f4fa8;outline-offset:2px}
'''
LEGACY_LINK_REPLACEMENT = '''      details.appendChild(message);
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
LEGACY_CSS_REPLACEMENT = '''.trip-extra .trip-check-link{margin:9px 0 0;display:table;border:1px solid #9db8ee;
  background:#eef4ff;color:#1f4fa8;border-radius:9px;padding:7px 10px;
  text-decoration:none;font-size:12px;font-weight:600}
'''

CIRCLE_LINK_REPLACEMENT = '''      const main=document.createElement("div");
      main.className="trip-extra-main";
      main.appendChild(message);
      if(trainCheck){
        const link=document.createElement("a");
        link.className="trip-check-link";
        link.href="https://t.me/Alarma_cmtbc_bot?start="+trainCheck;
        link.target="_blank";
        link.rel="noopener noreferrer";
        link.setAttribute("aria-label","Comprobar tren en Telegram");
        link.title="Comprobar tren en Telegram";
        link.innerHTML='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 .2C5.5 .2.2 5.5.2 12S5.5 23.8 12 23.8 23.8 18.5 23.8 12 18.5.2 12 .2Zm5.5 7.7-2 9.4c-.15.66-.55.82-1.1.5l-3-2.2-1.45 1.4c-.16.16-.3.3-.6.3l.22-3.05 5.55-5.02c.24-.21-.05-.33-.37-.12l-6.87 4.33-2.96-.92c-.65-.2-.66-.64.13-.95L16.6 7.1c.54-.2 1.01.13.84.8Z"/></svg>';
        main.appendChild(link);
      }
      details.appendChild(main);
'''
CIRCLE_CSS_REPLACEMENT = '''.trip-extra a{display:inline-block;margin-left:8px}
.trip-extra-main{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.trip-extra-main > span{flex:1;min-width:0}
.trip-extra .trip-check-link{margin:0;display:inline-flex;align-items:center;justify-content:center;
  flex:none;width:36px;height:36px;padding:0;border-radius:50%;
  color:#229ed9;text-decoration:none}
.trip-extra .trip-check-link svg{display:block;width:27px;height:27px;fill:currentColor}
.trip-extra .trip-check-link:focus-visible{outline:2px solid #1f4fa8;outline-offset:2px}
'''

CURRENT_DETAILS_TAIL = '''      const main=document.createElement("div");
      main.className="trip-extra-main";
      main.appendChild(message);
      if(trainCheck){
        const link=document.createElement("a");
        link.className="trip-check-link";
        link.href="https://t.me/Alarma_cmtbc_bot?start="+trainCheck;
        link.target="_blank";
        link.rel="noopener noreferrer";
        link.setAttribute("aria-label","Comprobar tren en Telegram");
        link.title="Comprobar tren en Telegram";
        link.innerHTML='<svg data-icon="message-circle" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/></svg>';
        main.appendChild(link);
      }
      details.appendChild(main);
      if(t.fuente_cambio) {
        const technicalRenfe=t.tipo==="tren" &&
          /^https:\/\/gtfsrt\.renfe\.com\//.test(t.fuente_cambio);
        if(technicalRenfe && t.linea==="C-1"){
          const source=document.createElement("a");
          source.href="https://tiempo-real.renfe.com/?lang=es";
          source.target="_blank";
          source.rel="noopener noreferrer";
          source.textContent="Consultar Cercanías en Renfe";
          details.appendChild(source);
        } else if(technicalRenfe){
          // MD realtime JSON is not a passenger page: omit empty attribution.
        } else {
          const source=document.createElement("a");
          source.href=t.fuente_cambio;
          source.target="_blank";
          source.rel="noopener noreferrer";
          source.textContent="Fuente";
          details.appendChild(source);
        }
      }
      extra.appendChild(details);'''
COMPACT_DETAILS_TAIL = '''      const main=document.createElement("div");
      main.className="trip-extra-main";
      const content=document.createElement("div");
      content.className="trip-extra-content";
      content.appendChild(message);
      main.appendChild(content);
      if(trainCheck){
        const link=document.createElement("a");
        link.className="trip-check-link";
        link.href="https://t.me/Alarma_cmtbc_bot?start="+trainCheck;
        link.target="_blank";
        link.rel="noopener noreferrer";
        link.setAttribute("aria-label","Comprobar tren en Telegram");
        link.title="Comprobar tren en Telegram";
        link.innerHTML='<svg data-icon="message-circle" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/></svg>';
        main.appendChild(link);
      }
      if(t.fuente_cambio) {
        const technicalRenfe=t.tipo==="tren" &&
          /^https:\/\/gtfsrt\.renfe\.com\//.test(t.fuente_cambio);
        if(technicalRenfe && t.linea==="C-1"){
          const source=document.createElement("a");
          source.href="https://tiempo-real.renfe.com/?lang=es";
          source.target="_blank";
          source.rel="noopener noreferrer";
          source.textContent="Consultar Cercanías en Renfe";
          source.className="trip-source-link";
          content.appendChild(source);
        } else if(technicalRenfe){
          // MD realtime JSON is not a passenger page: omit empty attribution.
        } else {
          const source=document.createElement("a");
          source.href=t.fuente_cambio;
          source.target="_blank";
          source.rel="noopener noreferrer";
          source.textContent="Fuente";
          source.className="trip-source-link";
          content.appendChild(source);
        }
      }
      details.appendChild(main);
      extra.appendChild(details);'''
CURRENT_DETAILS_CSS = '''.trip-extra a{display:inline-block;margin-left:8px}
.trip-extra-main{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.trip-extra-main > span{flex:1;min-width:0}
.trip-extra .trip-check-link{margin:0;display:inline-flex;align-items:center;justify-content:center;
  flex:none;width:36px;height:36px;padding:0;color:#6b7280;text-decoration:none}
.trip-extra .trip-check-link svg{display:block;width:18px;height:18px;fill:none;
  stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.trip-extra .trip-check-link:hover{color:#1f4fa8}
.trip-extra .trip-check-link:focus-visible{outline:2px solid #1f4fa8;outline-offset:2px}'''
COMPACT_DETAILS_CSS = '''.trip-extra a{display:inline-block;margin-left:8px}
.trip-extra-main{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}
.trip-extra-content{display:flex;flex:1;min-width:0;flex-direction:column;gap:2px}
.trip-extra-content > span{display:block}
.trip-extra .trip-source-link{display:block;margin:0;line-height:1.5}
.trip-extra .trip-check-link{margin:0;display:inline-flex;align-items:center;justify-content:center;
  flex:none;width:36px;height:36px;padding:0;color:#6b7280;text-decoration:none}
.trip-extra .trip-check-link svg{display:block;width:18px;height:18px;fill:none;
  stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.trip-extra .trip-check-link:hover{color:#1f4fa8}
.trip-extra .trip-check-link:focus-visible{outline:2px solid #1f4fa8;outline-offset:2px}'''

def compact_layout(source):
    """Convert the already-installed chat link into a compact, two-column details panel."""
    if 'className="trip-extra-content"' in source:
        if 'className="trip-source-link"' not in source:
            raise ValueError("Partially updated train details layout")
        return source
    for original, replacement in (
        (CURRENT_DETAILS_TAIL, COMPACT_DETAILS_TAIL),
        (CURRENT_DETAILS_CSS, COMPACT_DETAILS_CSS),
    ):
        if source.count(original) != 1:
            raise ValueError("Unexpected train details layout marker: {!r} count={}".format(
                original[:65], source.count(original)))
        source = source.replace(original, replacement, 1)
    return source

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
        if 'data-icon="message-circle"' in source:
            if 'Comprobar tren en Telegram' not in source:
                raise ValueError("Partially patched chat icon")
            return compact_layout(source)
        if 'className="trip-extra-main"' in source:
            replacements = (
                (CIRCLE_LINK_REPLACEMENT, LINK_REPLACEMENT),
                (CIRCLE_CSS_REPLACEMENT, CSS_REPLACEMENT),
            )
        elif '↗ Comprobar ahora en Telegram' in source:
            replacements = (
                (LEGACY_LINK_REPLACEMENT, LINK_REPLACEMENT),
                (LEGACY_CSS_REPLACEMENT, CSS_REPLACEMENT),
            )
        else:
            raise ValueError("Partially patched HTML found")
        for original, replacement in replacements:
            if source.count(original) != 1:
                raise ValueError("Unexpected Telegram UI marker: {!r} count={}".format(
                    original[:65], source.count(original)))
            source = source.replace(original, replacement, 1)
        return compact_layout(source)
    for original, replacement in MODIFICATIONS:
        if source.count(original) != 1:
            raise ValueError("Unexpected HTML shell marker: {!r} count={}".format(
                original[:65], source.count(original)))
        source = source.replace(original, replacement, 1)
    return compact_layout(source)


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
