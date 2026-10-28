#!/usr/bin/env python3
"""Transport timetable for El Puerto de Santa María, Cádiz and Jerez.
Production version from 2026-10-28; based on the CMTBC origin-destination tables.
"""
import json
import os
import re
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://siu.cmtbc.es/es/horarios_origen_destino.php"
CITIES = {"puerto": (8, "El Puerto"), "cadiz": (1, "Cádiz"), "jerez": (14, "Jerez")}
ROUTES = [(a, b) for a in CITIES for b in CITIES if a != b]
OUTPUT = Path(__file__).parent / "output" / "horarios_tres_ciudades.html"
WARNINGS_FILE = OUTPUT.parent / "transport_warning_report.json"
ALERT_STATE_FILE = OUTPUT.parent / "transport_last_alert.sha256"
# Source calendar codes. Unknown codes remain visible in red and trigger a report.
ALLOWED_DAYS = {"L-J", "L-V", "L-S", "L-D", "S", "D", "S-D-F", "V"}

PREFERENCES = {
    "puerto": {
        "tren": ["Estación FC"],
        "catamaran": ["Terminal Marítima El Puerto"],
        "bus": ["Pl. Toros-Hospital", "Intercambiador", "Estación FC", "Valdelagrana"],
    },
    "cadiz": {
        "tren": ["Plaza de Sevilla-Estación de Cádiz"],
        "catamaran": ["Terminal Marítima Cádiz"],
        "bus": ["Plaza de Sevilla-Estación de Cádiz", "Telegrafía-Estadio", "Pz.Asdrúbal", "Hospital-Segunda Ag."],
    },
    "jerez": {
        "tren": ["Estación de Jerez"],
        "bus": ["Estación de Jerez"],
    },
}


def source_url(a, b):
    return "{}?ida={}&vuelta={}".format(BASE_URL, CITIES[a][0], CITIES[b][0])


def fetch(url):
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
    r.raise_for_status()
    return r.text


def pick_stop(stops, times, city, kind):
    choices = PREFERENCES[city][kind]
    for wanted in choices:
        for stop, time in zip(stops, times):
            if wanted.casefold() in stop.casefold() and re.fullmatch(r"\d{1,2}:\d{2}", time):
                return time, stop
    for stop, time in zip(stops, times):
        if re.fullmatch(r"\d{1,2}:\d{2}", time):
            return time, stop
    return None


def station_time(stops, times):
    """Exact station stop, never silently substitute campus or La Granja."""
    for stop, time in zip(stops, times):
        if stop == "Estación de Jerez" and re.fullmatch(r"\d{1,2}:\d{2}", time):
            return time, stop
    raise ValueError("Bus or train does not stop at Estación de Jerez; check route")


def plaza_del_caballo_estimate(destination_time):
    """M-352 has no published Plaza del Caballo column in CMTBC origin-destination.
    Use the 7-minute difference between Plaza del Caballo (21:44)
    and La Granja (21:51) in the stop-by-stop M-352 schedule.
    Source: busmaps.com/en/spain/public_transit-line-M-352-2774540230-2813672500
    Mark estimated, never represent it as a primary official stop time.
    """
    dt = datetime.strptime(destination_time, "%H:%M")
    return (dt - timedelta(minutes=7)).strftime("%H:%M")


def parse(page, origin, destination):
    soup = BeautifulSoup(page, "html.parser")
    table = soup.find("table")
    if table is None:
        raise ValueError("No timetable table for {} -> {}".format(origin, destination))
    lines = table.find_all("tr")
    if len(lines) < 3:
        raise ValueError("Empty timetable table for {} -> {}".format(origin, destination))
    top = lines[0].find_all(["th", "td"], recursive=False)
    if len(top) < 5:
        raise ValueError("Unexpected header for {} -> {}".format(origin, destination))
    first_n, second_n = int(top[1].get("colspan", "1")), int(top[2].get("colspan", "1"))
    stop_titles = [c.get_text(" ", strip=True) for c in lines[1].find_all(["th", "td"], recursive=False)]
    if len(stop_titles) != first_n + second_n:
        raise ValueError("Unexpected stop columns for {} -> {}".format(origin, destination))

    trips = []
    dropped = []
    for tr in lines[2:]:
        cells = [c.get_text(" ", strip=True).replace("\xa0", " ") for c in tr.find_all("td", recursive=False)]
        if not cells:
            continue
        line = cells[0].strip()
        if line and line != "--" and len(cells) != first_n + second_n + 3:
            raise ValueError("Unexpected timetable row shape for {} -> {}: {}".format(
                origin, destination, cells[:3]))
        if not line or line in ("--", "Líneas"):
            continue
        kind = "tren" if line in ("C-1", "MD") else "catamaran" if line == "B-042" else "bus"
        stop_times = cells[1 : 1 + first_n + second_n]
        departing = pick_stop(stop_titles[:first_n], stop_times[:first_n], origin, kind)
        arriving = pick_stop(stop_titles[first_n:], stop_times[first_n:], destination, kind)
        if not departing or not arriving:
            dropped.append(line)
            continue

        estimated_arrival = False
        if destination == "jerez":
            if kind == "bus" and line == "M-352":
                # The source lists La Granja as the only timed Jerez stop;
                # use Plaza del Caballo on the same itinerary, explicitly estimated.
                if "La Granja" not in arriving[1]:
                    raise ValueError("M-352: unexpected final stop {}; verify itinerary".format(arriving[1]))
                arriving = (plaza_del_caballo_estimate(arriving[0]), "Plaza del Caballo")
                estimated_arrival = True
            else:
                try:
                    arriving = station_time(
                        stop_titles[first_n:], stop_times[first_n:])
                except ValueError as exc:
                    raise ValueError("{} -> {} line {}: {}".format(
                        origin, destination, line, exc)) from exc
        if origin == "jerez":
            try:
                departing = station_time(stop_titles[:first_n], stop_times[:first_n])
            except ValueError as exc:
                raise ValueError("{} -> {} line {}: {}".format(
                    origin, destination, line, exc)) from exc
        days = cells[-2].strip()
        warning = ""
        if days not in ALLOWED_DAYS:
            warning = "Código de días desconocido: {} (línea {})".format(days or "[vacío]", line)
        trips.append({
            "linea": line,
            "tipo": kind,
            "salida": departing[0],
            "llegada": arriving[0],
            "parada_salida": departing[1],
            "parada_llegada": arriving[1],
            "llegada_estimada": estimated_arrival,
            "dias": days,
            "aviso": warning,
        })
    if dropped:
        raise ValueError("Unparsed trips for {} -> {}: {}".format(origin, destination, dropped))
    if not trips:
        raise ValueError("No usable trips for {} -> {}".format(origin, destination))
    return sorted(trips, key=lambda t: (t["salida"], t["linea"])), dropped


HTML = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#2d6cdf">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Horarios Bahía">
<link rel="manifest" href="/transport/manifest.webmanifest">
<link rel="icon" href="/transport/icon-192.png" sizes="192x192" type="image/png">
<link rel="apple-touch-icon" href="/transport/icon-180.png">
<title>Horarios de transporte · Bahía de Cádiz</title>
<style>
:root{font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;color:#222;background:#f5f6f8}
*{box-sizing:border-box}
body{margin:0;padding:16px}
.wrapper{max-width:510px;margin:auto}
h1{font-size:26px;margin:4px 0 16px}
.controls{display:grid;gap:12px;margin-bottom:14px}
.route-selector{display:grid;grid-template-columns:minmax(0,1fr) 47px;gap:7px}
.direction-toggle{display:flex;align-items:center;justify-content:space-between;min-width:0;min-height:55px;background:#2d6cdf;color:white;border:1px solid #2d6cdf;border-radius:14px;padding:8px 11px;cursor:pointer;text-align:left}
.route-leg{display:grid;gap:3px;min-width:0}
.route-leg small{font-size:11px;opacity:.8;font-weight:450}
.route-leg strong{font-size:16px;line-height:1.1;font-weight:650;overflow-wrap:anywhere}
.route-arrow{font-size:20px;opacity:.9;flex:0 0 auto;margin:0 8px}
.route-list-toggle{width:47px;min-height:55px;border:1px solid #9db8ee;border-radius:14px;background:#eef4ff;color:#1f4fa8;font-size:23px;cursor:pointer}
.route-list-toggle[aria-expanded="true"]{background:#dce9ff}
.route-menu{display:grid;grid-template-columns:1fr;gap:6px;margin-top:-5px;border-radius:12px;background:white;border:1px solid #d7dbe3;padding:7px}
.route-menu[hidden]{display:none}
.route-choice{border:1px solid transparent;border-radius:9px;background:#fff;color:#333;text-align:left;padding:11px 12px;font-size:15px;cursor:pointer}
.route-choice:hover,.route-choice:focus{background:#eef4ff}
.route-choice.active{background:#eef4ff;border-color:#9db8ee;color:#1f4fa8;font-weight:650}
.days{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px}
.day-btn,.filter-chip{min-width:0;cursor:pointer;border-radius:100px;background:#fff;border:1px solid #d7dbe3;color:#4b5563;font-size:13px;line-height:1.25;padding:9px 5px;text-align:center}
.day-btn.active{background:#2d6cdf;border-color:#2d6cdf;color:#fff;font-weight:650}
.filters{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}
.filter-chip.active{background:#eef4ff;border-color:#9db8ee;color:#1f4fa8;font-weight:650}
.section{background:white;border:1px solid #ddd;border-radius:12px;padding:10px}
table{border-collapse:collapse;width:100%}
th{font-size:13px;color:#666;padding:7px 4px;text-align:center;border-bottom:1px solid #ddd}
td{padding:9px 5px;border-bottom:1px solid #eee;font-size:16px;text-align:center;vertical-align:middle}
tr:last-child td{border-bottom:none}
td:nth-child(3){font-size:14px;color:#444}
.small{display:block;color:#777;font-size:10px;line-height:1.25;margin-top:3px;max-width:160px;overflow-wrap:anywhere}
.empty-note{text-align:center;color:#666;font-size:14px;padding:18px 0}
.source-note{font-size:12px;color:#777;line-height:1.5;margin-top:12px}
.warning-banner{background:#fff0f0;border:1px solid #d34545;color:#a41515;border-radius:11px;padding:10px 12px;font-size:13px;line-height:1.4;margin-bottom:10px}
tr.uncertain{background:#fff0f0}
tr.uncertain td:nth-child(3){color:#b91c1c;font-weight:650}
.uncertain .day-warning{display:block;color:#b91c1c;font-size:11px;font-weight:650}
a{color:#1f4fa8}
.pwa-install{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:-6px 0 14px}
.pwa-install[hidden],.offline-notice[hidden]{display:none}
.install-btn{border:1px solid #9db8ee;background:#eef4ff;color:#1f4fa8;border-radius:10px;padding:8px 12px;font-size:13px;font-weight:650;cursor:pointer}
.offline-notice{background:#fff6e5;color:#804600;border:1px solid #e8c37b;border-radius:10px;padding:9px 12px;margin-bottom:11px;font-size:13px;line-height:1.4}
</style>
</head>
<body>
<main class="wrapper">
<h1>Horarios de transporte</h1>
<div class="pwa-install" id="pwaInstall" hidden>
  <button type="button" class="install-btn" id="installAppBtn">Instalar app</button>
</div>
<div class="offline-notice" id="offlineNotice" role="status" hidden>Sin conexión. Horarios guardados: pueden haber cambiado. Compruébalos antes de viajar.</div>
<div class="controls">
  <div class="route-selector">
    <button id="directionBtn" class="direction-toggle" type="button" title="Invertir trayecto" aria-label="Invertir trayecto">
      <span class="route-leg"><small>Desde</small><strong id="routeFrom">El Puerto</strong></span>
      <span class="route-arrow" aria-hidden="true">⇄</span>
      <span class="route-leg"><small>Hasta</small><strong id="routeTo">Cádiz</strong></span>
    </button>
    <button id="routeListBtn" class="route-list-toggle" type="button" aria-label="Elegir par de ciudades" aria-expanded="false" aria-controls="routeMenu">⌄</button>
  </div>
  <div class="route-menu" id="routeMenu" hidden>
    <button class="route-choice active" type="button" data-pair="puerto-cadiz">El Puerto ↔ Cádiz</button>
    <button class="route-choice" type="button" data-pair="puerto-jerez">El Puerto ↔ Jerez</button>
    <button class="route-choice" type="button" data-pair="cadiz-jerez">Cádiz ↔ Jerez</button>
  </div>
  <div class="days" aria-label="Día de viaje">
    <button type="button" class="day-btn active" data-day="lunes_jueves">Lun.–Jue.</button>
    <button type="button" class="day-btn" data-day="viernes">Viernes</button>
    <button type="button" class="day-btn" data-day="sabado">Sábado</button>
    <button type="button" class="day-btn" data-day="domingo">Dom./fest.</button>
  </div>
  <div class="filters" aria-label="Transporte">
    <button type="button" class="filter-chip active" data-type="catamaran">⛴ Barco</button>
    <button type="button" class="filter-chip active" data-type="bus">🚌 Bus</button>
    <button type="button" class="filter-chip active" data-type="tren">🚆 Tren</button>
  </div>
</div>
<div id="warningSummary" class="warning-banner" role="alert" hidden></div>
<div class="section">
 <table><thead><tr><th>Salida</th><th>Llegada</th><th>Línea</th></tr></thead><tbody id="schedule"></tbody></table>
 <div class="empty-note" id="empty" hidden>No hay servicios para los filtros elegidos.</div>
</div>
<p class="source-note">
 Horas de paso en la parada indicada; en autobús pueden variar por el tráfico.
 Las horas marcadas con ≈ son aproximadas.
 Para días festivos, comprueba las excepciones.
 <a id="source" href="#" target="_blank" rel="noopener noreferrer">Fuente: Consorcio de Transportes</a>.
 <span>Consultado el __UPDATED__.</span>
</p>
</main>
<script>
"use strict";
const DATA = __TRANSPORT_DATA__;
const NAMES = {"puerto":"El Puerto","cadiz":"Cádiz","jerez":"Jerez"};
const ALLOWED_DAYS = ["L-J","L-V","L-S","L-D","S","D","S-D-F","V"];
function displayStop(stop, city) {
  if (city === "puerto") {
    if (stop === "Pl. Toros-Hospital") return "Plaza de Toros";
    if (stop === "Estación FC" || stop === "Intercambiador El Pto. de Sta. María")
      return "Estación El Puerto";
  }
  if (city === "cadiz" && stop === "Plaza de Sevilla-Estación de Cádiz") return "Estación de Cádiz";
  return stop;
}
const PREFERRED = {
  "puerto":{"bus":"Pl. Toros-Hospital","tren":"Estación FC","catamaran":"Terminal Marítima El Puerto"},
  "cadiz":{"bus":"Plaza de Sevilla-Estación de Cádiz","tren":"Plaza de Sevilla-Estación de Cádiz","catamaran":"Terminal Marítima Cádiz"},
  "jerez":{"bus":"Estación de Jerez","tren":"Estación de Jerez"}
};
const body = document.getElementById("schedule");
const routeMenu = document.getElementById("routeMenu");
const routeListBtn = document.getElementById("routeListBtn");
let fromCity = "puerto", toCity = "cadiz";
let day = "lunes_jueves";
let types = new Set(["bus","tren","catamaran"]);
function currentPair() {
  return [fromCity,toCity].sort().join("-");
}
function setMenu(open) {
  routeMenu.hidden = !open;
  routeListBtn.setAttribute("aria-expanded",String(open));
}
function updateRouteControls() {
  document.getElementById("routeFrom").textContent=NAMES[fromCity];
  document.getElementById("routeTo").textContent=NAMES[toCity];
  document.querySelectorAll(".route-choice").forEach(b=>{
    const selected=b.dataset.pair.split("-").every(city=>[fromCity,toCity].includes(city));
    b.classList.toggle("active",selected);
    b.setAttribute("aria-pressed",String(selected));
  });
}
function operates(code) {
  if (!ALLOWED_DAYS.includes(code)) return true; // unverified: visible in red on every day
  if (code === "L-D") return true;
  if (day === "lunes_jueves") return ["L-V","L-S","L-J","L-D"].includes(code);
  if (day === "viernes") return ["L-V","L-S","L-D","V"].includes(code);
  if (day === "sabado") return ["L-S","S-D-F","L-D","S"].includes(code);
  return ["S-D-F","L-D","D"].includes(code);
}
function tdWithStop(time, stop, city, type, estimated=false) {
  const td=document.createElement("td");
  td.appendChild(document.createTextNode((estimated ? "≈" : "")+time));
  if (estimated) td.title="Hora aproximada de paso. Confirma en la parada.";
  if (stop) {
    const small=document.createElement("small");
    small.className="small";
    small.textContent=displayStop(stop,city);
    if (small.textContent!==stop) small.title="Fuente: "+stop;
    td.appendChild(small);
  }
  return td;
}
function update() {
  const key=fromCity+"-"+toCity;
  updateRouteControls();
  const routeTrips=DATA[key]||[];
  const warnings=routeTrips.filter(t=>t.aviso);
  const banner=document.getElementById("warningSummary");
  banner.hidden=warnings.length===0;
  banner.textContent=warnings.length
      ? "⚠ "+warnings.length+" servicio(s) con calendario sin verificar. Se muestran en rojo para revisión."
      : "";
  const trips=routeTrips.filter(t=>types.has(t.tipo)&&operates(t.dias));
  body.replaceChildren();
  const fragment=document.createDocumentFragment();
  for(const t of trips) {
    const tr=document.createElement("tr");
    if(t.aviso){ tr.classList.add("uncertain"); tr.title=t.aviso; }
    tr.appendChild(tdWithStop(t.salida,t.parada_salida,fromCity,t.tipo));
    tr.appendChild(tdWithStop(t.llegada,t.parada_llegada,toCity,t.tipo,t.llegada_estimada));
    const line=document.createElement("td");
    line.appendChild(document.createTextNode(t.linea));
    const small=document.createElement("small");
    small.className="small";
    small.textContent=t.aviso ? "⚠ "+(t.dias||"?") : t.dias;
    if(t.aviso) {small.classList.add("day-warning"); small.title=t.aviso;}
    line.appendChild(small);
    tr.appendChild(line);
    fragment.appendChild(tr);
  }
  body.appendChild(fragment);
  document.getElementById("empty").hidden=trips.length>0;
  document.getElementById("source").href="https://siu.cmtbc.es/es/horarios_origen_destino.php?ida="+{"puerto":8,"cadiz":1,"jerez":14}[fromCity]+"&vuelta="+{"puerto":8,"cadiz":1,"jerez":14}[toCity];
}
document.getElementById("directionBtn").addEventListener("click",()=>{
  [fromCity,toCity]=[toCity,fromCity];
  setMenu(false);
  update();
});
routeListBtn.addEventListener("click",()=>{
  setMenu(routeMenu.hidden);
});
document.querySelectorAll(".route-choice").forEach(b=>b.addEventListener("click",()=>{
  const [a,c]=b.dataset.pair.split("-");
  if(fromCity===a||fromCity===c) {
    toCity=fromCity===a?c:a;
  } else {
    fromCity=a;toCity=c;
  }
  setMenu(false);
  update();
}));
document.addEventListener("keydown",e=>{
  if(e.key==="Escape" && !routeMenu.hidden) {
    setMenu(false);
    routeListBtn.focus();
  }
});
document.addEventListener("click",e=>{
  if(!routeMenu.hidden && !e.target.closest(".route-menu,.route-list-toggle")) setMenu(false);
});
document.querySelectorAll(".day-btn").forEach(btn=>btn.addEventListener("click",()=>{
  day=btn.dataset.day;
  document.querySelectorAll(".day-btn").forEach(b=>{b.classList.toggle("active",b===btn);b.setAttribute("aria-pressed",String(b===btn));});
  update();
}));
document.querySelectorAll(".filter-chip").forEach(btn=>btn.addEventListener("click",()=>{
  const type=btn.dataset.type;
  if(types.size===3)types=new Set([type]);
  else if(types.size===1&&types.has(type))types=new Set(["bus","tren","catamaran"]);
  else if(types.has(type))types.delete(type);
  else types.add(type);
  document.querySelectorAll(".filter-chip").forEach(b=>{const enabled=types.has(b.dataset.type);b.classList.toggle("active",enabled);b.setAttribute("aria-pressed",String(enabled));});
  update();
}));
document.querySelectorAll(".day-btn,.filter-chip").forEach(b=>b.setAttribute("aria-pressed",String(b.classList.contains("active"))));
// PWA setup is part of the generated HTML so each daily update preserves installation.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/transport/sw.js", {scope:"/transport/"}).catch(e=>console.warn("PWA unavailable",e));
}
const pwaInstall=document.getElementById("pwaInstall");
const standalone=window.matchMedia("(display-mode: standalone)").matches || navigator.standalone===true;
let deferredInstall=null;
// Show a real install button only when the browser exposes a usable install prompt.
// In-app browsers cannot install PWAs: never show a misleading button there.
window.addEventListener("beforeinstallprompt",e=>{
  e.preventDefault();
  deferredInstall=e;
  if(!standalone)pwaInstall.hidden=false;
});
document.getElementById("installAppBtn").addEventListener("click",async()=>{
  if(!deferredInstall){pwaInstall.hidden=true;return;}
  const prompt=deferredInstall;
  deferredInstall=null;
  pwaInstall.hidden=true;
  await prompt.prompt();
  await prompt.userChoice;
});
window.addEventListener("appinstalled",()=>{
  pwaInstall.hidden=true;
  deferredInstall=null;
});
const offlineNotice=document.getElementById("offlineNotice");
function updateConnection(){offlineNotice.hidden=navigator.onLine;}
window.addEventListener("offline",updateConnection);
window.addEventListener("online",updateConnection);
updateConnection();
update();
</script>
</body>
</html>"""


def notify_telegram(message):
    """Send into the existing transport Telegram bot, if configured by systemd."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    topic_id = os.getenv("TELEGRAM_TOPIC_ID")
    if not token or not chat_id:
        print("Telegram is not configured in this environment; report saved locally.", flush=True)
        return False
    payload = {"chat_id": chat_id, "text": message[:3500]}
    if topic_id:
        payload["message_thread_id"] = topic_id
    r = requests.post(
        "https://api.telegram.org/bot{}/sendMessage".format(token),
        data=payload, timeout=15)
    r.raise_for_status()
    result = r.json()
    if not result.get("ok"):
        raise RuntimeError("Telegram rejected alert: {}".format(result.get("description", "unknown")))
    return True


def report_issues(issues):
    """Store full diagnostics. Notify once for each newly observed set of issues."""
    WARNINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    report = {"checked_at": datetime.now().isoformat(timespec="seconds"), "issues": issues}
    WARNINGS_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if not issues:
        ALERT_STATE_FILE.unlink(missing_ok=True)
        return
    signature = hashlib.sha256(
        json.dumps(issues, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    if ALERT_STATE_FILE.exists() and ALERT_STATE_FILE.read_text().strip() == signature:
        print("Previously reported transport warning; no duplicate Telegram alert", flush=True)
        return
    message = "⚠️ Transport: требуется проверка расписания.\n" + "\n".join(
        issue["route"] + ": " + issue["detail"] for issue in issues[:15])
    if len(issues) > 15:
        message += "\n… и ещё {} предупреждений".format(len(issues) - 15)
    try:
        if notify_telegram(message):
            ALERT_STATE_FILE.write_text(signature, encoding="utf-8")
    except Exception as exc:
        print("Failed to send Telegram alert: {}".format(exc), flush=True)


def build():
    data = {}
    issues = []
    try:
        for origin, destination in ROUTES:
            url = source_url(origin, destination)
            trips, dropped = parse(fetch(url), origin, destination)
            key = origin + "-" + destination
            data[key] = trips
            for trip in trips:
                if trip["aviso"]:
                    issues.append({"route": key, "detail": trip["aviso"]})
    except Exception as exc:
        report_issues([{"route": "ERROR", "detail": str(exc)}])
        raise
    report_issues(issues)
    for origin, destination in ROUTES:
        key = origin + "-" + destination
        trips = data[key]
        dropped = []
        print("{}: {} trips ({} bus, {} train, {} boat), dropped {}: {}".format(
            key, len(trips),
            sum(t["tipo"] == "bus" for t in trips),
            sum(t["tipo"] == "tren" for t in trips),
            sum(t["tipo"] == "catamaran" for t in trips),
            len(dropped), ", ".join(dropped[:8])), flush=True)
    output = HTML.replace("__TRANSPORT_DATA__", json.dumps(data, ensure_ascii=False).replace("<", "\\u003c"))
    output = output.replace("__UPDATED__", datetime.now().strftime("%d/%m/%Y"))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(output, encoding="utf-8")
    print("OUTPUT", OUTPUT, len(output), "bytes", flush=True)


if __name__ == "__main__":
    build()
