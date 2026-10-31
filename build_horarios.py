#!/usr/bin/env python3
"""Transport timetable for El Puerto de Santa María, Cádiz and Jerez.
Production version from 2026-10-28; based on the CMTBC origin-destination tables.
Android PWA install analysis: scripts/compare_android_install.cjs.
"""
import json
import os
import re
import hashlib
import argparse
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from transport_updates import apply_changes, date_now
from renfe_schedule import replace_ctan_trains, reference_day

BASE_URL = "https://siu.cmtbc.es/es/horarios_origen_destino.php"
CITIES = {"puerto": (8, "El Puerto"), "cadiz": (1, "Cádiz"), "jerez": (14, "Jerez")}
ROUTES = [(a, b) for a in CITIES for b in CITIES if a != b]
OUTPUT = Path(__file__).parent / "output" / "horarios_tres_ciudades.html"
DATA_OUTPUT = OUTPUT.parent / "transport_data.json"
WARNINGS_FILE = OUTPUT.parent / "transport_warning_report.json"
ALERT_STATE_FILE = OUTPUT.parent / "transport_last_alert.sha256"
OUTAGE_STATE_FILE = OUTPUT.parent / "transport_cmtbc_outage_state.json"
# This is shown on each cached bus/boat row, not one Telegram issue per row.
CMTBC_STALE_NOTICE = ("Consorcio sin respuesta: horario de autobús/barco "
                      "no verificado en esta actualización")
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
    """Bound CMTBC requests; retry only transient network failures."""
    for attempt in range(2):
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"},
                             timeout=(7, 15))
            r.raise_for_status()
            return r.text
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 0:
                time.sleep(2)
                continue
            raise
        except requests.HTTPError as exc:
            # The origin occasionally returns temporary gateway/rate-limit
            # errors. A single retry avoids an unnecessary outage alert.
            code = exc.response.status_code if exc.response is not None else None
            if attempt == 0 and code in (429, 500, 502, 503, 504):
                time.sleep(2)
                continue
            raise


def cached_ctan_route(route):
    """Use last published bus/boat rows only, with explicit stale-data warning.

    A lost CMTBC response must never block a valid Renfe refresh or display
    last known bus times as confirmed. Do not cache train times here.
    """
    warning = CMTBC_STALE_NOTICE
    for path in (DATA_OUTPUT, Path("/srv/www/transport/transport_data.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            entries = payload["data"][route]
            if not isinstance(entries, list):
                continue
            rows = []
            for item in entries:
                if not isinstance(item, dict) or item.get("tipo") not in ("bus", "catamaran"):
                    continue
                if not all(k in item for k in ("linea", "salida", "llegada", "dias")):
                    continue
                row = item.copy()
                row["aviso"] = warning
                rows.append(row)
            if rows:
                return rows
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None


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
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Horarios Bahía">
<link rel="manifest" href="/transport/manifest.json?v=2">
<link rel="icon" href="/transport/icon-192-rgb.png" sizes="192x192" type="image/png">
<link rel="apple-touch-icon" href="/transport/icon-180.png">
<title>Horarios de transporte · Bahía de Cádiz</title>
<style>
:root{font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;color:#222;background:#f5f6f8}
*{box-sizing:border-box}
body{margin:0;padding:16px}
.wrapper{max-width:510px;margin:auto}
h1{font-size:clamp(23px,5vw,26px);margin:4px 0 5px;text-align:center;line-height:1.2}
.page-heading{margin-bottom:17px}
.page-meta{display:flex;align-items:center;justify-content:center;gap:9px;flex-wrap:wrap;min-height:24px}
.area-label{color:#697486;font-size:12px;letter-spacing:.01em}
.install-link{border:0;background:none;color:#1f4fa8;font-weight:600;font-size:12px;padding:4px 5px;cursor:pointer;text-decoration:underline;text-underline-offset:3px}
.install-help{position:relative;margin-top:9px;padding:11px 32px 11px 12px;border-radius:10px;background:#fff;border:1px solid #d7dbe3;color:#4b5563;font-size:12px;line-height:1.5}
.install-help p{margin:0}
.install-help button{position:absolute;top:5px;right:5px;border:0;background:none;color:#6b7280;font-size:20px;cursor:pointer;min-width:30px;min-height:30px}
.install-help[hidden],.install-link[hidden]{display:none}
.controls{display:grid;gap:12px;margin-bottom:14px}
.route-selector{display:grid;grid-template-columns:minmax(0,1fr) 47px;gap:7px}
.direction-toggle{display:flex;align-items:center;justify-content:space-between;min-width:0;min-height:55px;background:#2d6cdf;color:white;border:1px solid #2d6cdf;border-radius:14px;padding:8px 11px;cursor:pointer;text-align:left}
.route-leg{display:grid;gap:3px;min-width:0}
.route-leg small{font-size:11px;opacity:.8;font-weight:450}
.route-leg strong{font-size:16px;line-height:1.1;font-weight:650;overflow-wrap:anywhere}
.route-arrow{font-size:20px;opacity:.9;flex:0 0 auto;margin:0 8px}
.route-list-toggle{width:47px;min-height:55px;border:1px solid #9db8ee;border-radius:14px;background:#eef4ff;color:#1f4fa8;font-size:23px;cursor:pointer}
.route-list-toggle[aria-expanded="true"]{background:#dce9ff}
.route-chevron{display:inline-block;width:11px;height:11px;border-right:2.5px solid currentColor;border-bottom:2.5px solid currentColor;transform:rotate(45deg) translate(-2px,-2px);transition:transform .15s}
.route-list-toggle[aria-expanded="true"] .route-chevron{transform:rotate(225deg) translate(-2px,-2px)}
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
.reference-date{font-size:12px;color:#64748b;margin-top:-4px;margin-bottom:2px}
.reference-meta{display:flex;flex-wrap:wrap;align-items:center;gap:5px 14px}
.maritime-operational{color:#247343}
.maritime-affected{color:#a72121;font-weight:600}
.maritime-unknown{color:#91600b}
.official-alert{font-size:12px;color:#855b08;font-weight:600}
.official-alert a{color:inherit;text-decoration:underline;text-underline-offset:2px}
.reference-date[hidden],.status-legend[hidden],.trip-extra[hidden]{display:none}
.status-legend{display:flex;gap:7px 12px;align-items:center;flex-wrap:wrap;margin:0 1px 10px;padding:9px 10px;border:1px solid #e1e5ec;border-radius:10px;background:#fff;font-size:11px;color:#596474}
.status-legend span{display:inline-flex;align-items:center;gap:5px;white-space:nowrap}
.status-legend .legend-hint{margin-left:auto;color:#778395}
.status-dot{display:inline-block;width:11px;height:11px;border-radius:3px}
.status-dot.cancelled{background:#f1a3a3}
.status-dot.changed{background:#eac565}
tr.uncertain,tr.service-warning,tr.service-confirmed{background:#fff3d1}
tr.service-cancelled{background:#ffe5e5}
tr.service-cancelled td:nth-child(3){color:#a72121;font-weight:650}
tr.trip-expandable{cursor:pointer}
tr.trip-expandable:focus-visible{outline:2px solid #1f4fa8;outline-offset:-2px}
.trip-info{color:#6b7280;font-size:12px;margin-left:5px;font-weight:normal}
.trip-extra td{padding:10px 12px;background:#fffaf1;color:#5f4d21;text-align:left;font-size:12px;line-height:1.5;overflow-wrap:anywhere}
.trip-extra.cancelled td{background:#fff2f2;color:#8b2323}
.trip-extra a{display:inline-block;margin-left:8px}

a{color:#1f4fa8}
.offline-notice[hidden]{display:none}
.offline-notice{background:#fff6e5;color:#804600;border:1px solid #e8c37b;border-radius:10px;padding:9px 12px;margin-bottom:11px;font-size:13px;line-height:1.4}
</style>
</head>
<body>
<main class="wrapper">
<header class="page-heading">
  <h1>Horarios de transporte</h1>
  <div class="page-meta">
    <span class="area-label">El Puerto · Cádiz · Jerez</span>
    <button type="button" class="install-link" id="installButton" hidden>Instalar app</button>
  </div>
  <div class="install-help" id="installHelp" hidden role="status">
    <button type="button" id="closeInstallHelp" aria-label="Cerrar instrucciones">×</button>
    <p id="installInstructions"></p>
  </div>
</header>
<div class="offline-notice" id="offlineNotice" role="status" hidden>Sin conexión. Horarios guardados: pueden haber cambiado. Compruébalos antes de viajar.</div>
<div class="controls">
  <div class="route-selector">
    <button id="directionBtn" class="direction-toggle" type="button" title="Invertir trayecto" aria-label="Invertir trayecto">
      <span class="route-leg"><small>Desde</small><strong id="routeFrom">El Puerto</strong></span>
      <span class="route-arrow" aria-hidden="true">⇄</span>
      <span class="route-leg"><small>Hasta</small><strong id="routeTo">Cádiz</strong></span>
    </button>
    <button id="routeListBtn" class="route-list-toggle" type="button" aria-label="Elegir par de ciudades" aria-expanded="false" aria-controls="routeMenu"><span class="route-chevron" aria-hidden="true"></span></button>
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
  <div class="reference-meta">
    <div id="trainReference" class="reference-date" hidden></div>
    <div id="boatReference" class="reference-date" hidden></div>
    <div id="officialAlerts" class="official-alert" hidden></div>
  </div>
</div>
<div id="warningSummary" class="status-legend" aria-label="Leyenda de cambios" hidden>
  <span><i class="status-dot cancelled" aria-hidden="true"></i>Cancelado</span>
  <span><i class="status-dot changed" aria-hidden="true"></i>Cambio / aviso</span>
  <span class="legend-hint">ⓘ Toca para ver más</span>
</div>
<div class="section">
 <table><thead><tr><th>Salida</th><th>Llegada</th><th>Línea</th></tr></thead><tbody id="schedule"></tbody></table>
 <div class="empty-note" id="empty" hidden>No hay servicios para los filtros elegidos.</div>
</div>
<p class="source-note">
 Horarios previstos. Los autobuses pueden variar por el tráfico; ≈ indica una hora estimada.
 En festivos, consulta los avisos.
 <a id="source" href="#" target="_blank" rel="noopener noreferrer">Consorcio de Transportes</a>
 · Datos ferroviarios: Renfe (CC BY 4.0).
 <span id="serviceStatus"></span>
</p>
</main>
<script>
"use strict";
let DATA = __TRANSPORT_DATA__;
let SERVICE_META = __SERVICE_META__;
function spanishToday() {
  return new Intl.DateTimeFormat("sv-SE", {timeZone:"Europe/Madrid",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
}
function todayGroup() {
  const weekday=new Intl.DateTimeFormat("en-US",{timeZone:"Europe/Madrid",weekday:"short"}).format(new Date());
  return weekday==="Fri"?"viernes":weekday==="Sat"?"sabado":weekday==="Sun"?"domingo":"lunes_jueves";
}
function currentServiceStatus(t) {
  const checked=Date.parse(SERVICE_META.checked_at||"");
  const feedFresh=Number.isFinite(checked)&&Date.now()>=checked&&Date.now()-checked<=45*60*1000;
  if(t.tipo==="catamaran" && day===todayGroup() && SERVICE_META.date===spanishToday()){
    const verified=Date.parse((SERVICE_META.maritime||{}).checked_at||"");
    if(!Number.isFinite(verified)||Date.now()<verified||Date.now()-verified>45*60*1000){
      return "warning"; // Never show stale B-042 information as confirmed.
    }
  }
  return SERVICE_META.date===spanishToday() && day===todayGroup() && t.fecha_cambio===spanishToday()
      && (t.tipo!=="tren"||feedFresh) ? (t.estado||"") : "";
}
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
let day = todayGroup();
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
  const trips=routeTrips.filter(t=>types.has(t.tipo)&&operates(t.dias));
  trips.sort((a,b)=>{
    const at=currentServiceStatus(a)==="confirmed"?(a.salida_actual||a.salida):a.salida;
    const bt=currentServiceStatus(b)==="confirmed"?(b.salida_actual||b.salida):b.salida;
    return at.localeCompare(bt)||a.linea.localeCompare(b.linea);
  });
  const flags=trips.filter(t=>t.aviso||currentServiceStatus(t));
  document.getElementById("warningSummary").hidden=flags.length===0;
  const reference=document.getElementById("trainReference");
  const dates=[...new Set(trips.filter(t=>t.tipo==="tren"&&t.fecha_servicio)
    .map(t=>t.fecha_servicio))].sort();
  reference.hidden=dates.length===0;
  reference.textContent=dates.length
    ? "Trenes Renfe · horarios del "+dates.map(d=>d.split("-").reverse().join("/")).join(", ")
    : "";
  const alertBox=document.getElementById("officialAlerts");
  alertBox.replaceChildren();
  const activeAlerts=day===todayGroup()
    ? (SERVICE_META.official_alerts||[]).filter(a=>a.date===spanishToday())
    : [];
  alertBox.hidden=activeAlerts.length===0;
  for(const alert of activeAlerts){
    const link=document.createElement("a");
    link.href=alert.source;
    link.target="_blank";
    link.rel="noopener noreferrer";
    link.textContent="⚠ "+alert.title+" · comprobar trenes";
    alertBox.appendChild(link);
  }
  const marine=document.getElementById("boatReference");
  marine.hidden=!types.has("catamaran");
  marine.className="reference-date";
  if(!marine.hidden){
    const state=SERVICE_META.maritime||{};
    const last=Date.parse(state.checked_at||"");
    const fresh=Number.isFinite(last)&&Date.now()>=last&&Date.now()-last<=45*60*1000;
    const status=fresh?state.status:"unknown";
    if(status==="operational"){
      marine.textContent="⛴ B-042 · Operativo";
      marine.classList.add("maritime-operational");
    }else if(status==="affected"){
      marine.textContent="⛴ B-042 · Incidencias";
      marine.classList.add("maritime-affected");
    }else{
      marine.textContent="⛴ B-042 · Sin verificar";
      marine.classList.add("maritime-unknown");
    }
  }
  body.replaceChildren();
  const fragment=document.createDocumentFragment();
  for(const t of trips) {
    const tr=document.createElement("tr");
    const status=currentServiceStatus(t);
    const marked=Boolean(status||t.aviso);
    const cancelled=status==="cancelled";
    if(cancelled) tr.classList.add("service-cancelled");
    else if(marked) tr.classList.add("service-warning");
    const actual=status==="confirmed";
    const dep=tdWithStop(actual&&t.salida_actual?t.salida_actual:t.salida,
      t.parada_salida,fromCity,t.tipo);
    const arr=tdWithStop(actual&&t.llegada_actual?t.llegada_actual:t.llegada,
      t.parada_llegada,toCity,t.tipo,t.llegada_estimada&&!actual);
    tr.appendChild(dep);
    tr.appendChild(arr);
    const line=document.createElement("td");
    line.appendChild(document.createTextNode(t.linea));
    if(t.tipo!=="tren") {
      const small=document.createElement("small");
      small.className="small";
      small.textContent=t.dias||"?";
      line.appendChild(small);
    }
    if(marked) {
      const info=document.createElement("span");
      info.className="trip-info";
      info.textContent="ⓘ";
      info.setAttribute("aria-hidden","true");
      line.appendChild(info);
    }
    tr.appendChild(line);
    fragment.appendChild(tr);
    if(marked) {
      const extra=document.createElement("tr");
      extra.className="trip-extra"+(cancelled?" cancelled":"");
      extra.hidden=true;
      const details=document.createElement("td");
      details.colSpan=3;
      const message=document.createElement("span");
      message.textContent=t.detalle||t.aviso||
        (cancelled?"Servicio cancelado.":"Comprueba este servicio antes de viajar.");
      details.appendChild(message);
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
      extra.appendChild(details);
      fragment.appendChild(extra);
      tr.classList.add("trip-expandable");
      tr.tabIndex=0;
      tr.setAttribute("aria-expanded","false");
      tr.setAttribute("aria-label",t.linea+": "+(cancelled?"cancelado":"cambios o aviso")+". Ver detalles");
      const toggle=()=>{
        extra.hidden=!extra.hidden;
        tr.setAttribute("aria-expanded",String(!extra.hidden));
      };
      tr.addEventListener("click",toggle);
      tr.addEventListener("keydown",event=>{
        if(event.key==="Enter"||event.key===" ") {
          event.preventDefault();
          toggle();
        }
      });
    }
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
document.querySelectorAll(".day-btn").forEach(b=>b.classList.toggle("active",b.dataset.day===day));
document.querySelectorAll(".day-btn,.filter-chip").forEach(b=>b.setAttribute("aria-pressed",String(b.classList.contains("active"))));
const serviceStatus=document.getElementById("serviceStatus");
function renderSourceStatus() {
  const checked=Date.parse(SERVICE_META.checked_at||"");
  const stale=!Number.isFinite(checked)||Date.now()-checked>45*60*1000||Date.now()<checked;
  serviceStatus.textContent=SERVICE_META.checked_at
    ? " Datos: "+SERVICE_META.checked_at.replace("T"," ").slice(0,16)+" (España)."+
      (stale?" La última comprobación es antigua.":"")+
      (SERVICE_META.issues?" Algunas fuentes no respondieron.":"")
    : " Cambios en tiempo real no disponibles.";
}
renderSourceStatus();
// PWA setup is part of the generated HTML so each daily update preserves installation.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/transport/sw.js", {scope:"/transport/"}).catch(e=>console.warn("PWA unavailable",e));
}
// Chrome/Android: native install prompt when the browser grants one.
// Browsers without beforeinstallprompt: show short menu instructions instead.
const installButton=document.getElementById("installButton");
const installHelp=document.getElementById("installHelp");
const installInstructions=document.getElementById("installInstructions");
let deferredInstallPrompt=null;
const installedMode=()=>window.matchMedia("(display-mode: standalone)").matches||
  window.navigator.standalone===true;
function updateInstallVisibility(){
  // Only advertise installation when Chrome actually offers its native prompt.
  // A browser-only shortcut must not be presented as an installable app.
  installButton.hidden=installedMode()||!deferredInstallPrompt;
  if(installedMode())installHelp.hidden=true;
}
window.addEventListener("beforeinstallprompt",event=>{
  event.preventDefault();
  deferredInstallPrompt=event;
  updateInstallVisibility();
});
window.addEventListener("appinstalled",()=>{
  deferredInstallPrompt=null;
  installButton.hidden=true;
  installHelp.hidden=true;
});
installButton.addEventListener("click",async()=>{
  if(deferredInstallPrompt){
    const prompt=deferredInstallPrompt;
    deferredInstallPrompt=null;
    try{
      const choice=await prompt.prompt();
      if(choice&&choice.outcome==="accepted"){
        installHelp.hidden=true;
        return;
      }
    }catch(error){console.warn("Install prompt unavailable",error);}
  }
  const ios=/iPhone|iPad|iPod/i.test(navigator.userAgent);
  installInstructions.textContent=ios
    ? "En Safari, toca Compartir y elige «Añadir a pantalla de inicio»."
    : "En Chrome, abre el menú ⋮ y elige «Instalar aplicación» o «Añadir a pantalla de inicio».";
  installHelp.hidden=false;
});
document.getElementById("closeInstallHelp").addEventListener("click",()=>{
  installHelp.hidden=true;
});
updateInstallVisibility();
const offlineNotice=document.getElementById("offlineNotice");
function updateConnection(){offlineNotice.hidden=navigator.onLine;}
window.addEventListener("offline",updateConnection);
window.addEventListener("online",updateConnection);
updateConnection();
update();
// The HTML is a static shell. Fetch updated JSON from the VPS without reloading.
async function refreshData() {
  try {
    const response=await fetch("./transport_data.json",{cache:"no-store"});
    if(!response.ok)throw new Error("HTTP "+response.status);
    const payload=await response.json();
    if(!payload||!payload.data||typeof payload.data!=="object"||
       !payload.meta||!payload.meta.checked_at)throw new Error("Invalid timetable JSON");
    // A malformed JSON should not replace the last usable schedule.
    DATA=payload.data;
    SERVICE_META=payload.meta;
    renderSourceStatus();
    update();
  } catch(e) {
    console.warn("No se pudo actualizar el horario",e);
    renderSourceStatus();
    serviceStatus.textContent+=" Sin datos nuevos; comprueba el horario antes de viajar.";
  }
}
refreshData();
setInterval(()=>{if(document.visibilityState==="visible")refreshData();},60*1000);
document.addEventListener("visibilitychange",()=>{if(document.visibilityState==="visible")refreshData();});
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
    payload = {
        "chat_id": chat_id, "text": message[:3500],
        # No Telegram preview cards or apparent JSON file attachments.
        "link_preview_options": json.dumps({"is_disabled": True}),
    }
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


def _filter_short_cmtbc_outages(issues, now):
    """Alert only after two consecutive refreshes fail for the same route.

    Pending outages still appear in the local diagnostics and in the
    passenger-facing cached bus/boat warnings. Other source errors
    are reported immediately. Missed refreshes beyond 25 minutes break
    the sequence; duplicate rows within one refresh never increment it.
    """
    OUTAGE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        raw = json.loads(OUTAGE_STATE_FILE.read_text(encoding="utf-8"))
        previous = raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        previous = {}

    failing = {}
    immediate = []
    for issue in issues:
        if (issue["route"] != "ERROR" and
                issue["detail"].startswith("CMTBC sin respuesta; autobuses/barcos")):
            failing[issue["route"]] = issue
        else:
            immediate.append(issue)

    # A fatal, incomplete refresh cannot establish that routes recovered.
    if any(item["route"] == "ERROR" for item in issues):
        return issues, [], []

    current = {}
    confirmed = []
    pending = []
    for route, issue in sorted(failing.items()):
        old = previous.get(route, {})
        if not isinstance(old, dict):
            old = {}
        count = 1
        try:
            last = datetime.fromisoformat(old["last_seen"])
            age = (now - last).total_seconds()
            if 0 <= age <= 25 * 60:
                count = max(0, int(old.get("count", 0))) + 1
        except (TypeError, KeyError, ValueError, OverflowError):
            pass
        current[route] = {"count": count, "last_seen": now.isoformat()}
        if count >= 2:
            # Stable text across HTTP 500/503/429: a changed HTTP code
            # does not create another Telegram alert during one outage.
            confirmed.append({
                "route": route,
                "detail": "CMTBC sin respuesta en dos comprobaciones consecutivas; "
                          "horario de autobús/barco no verificado",
            })
        else:
            pending.append({"route": route, "count": count})

    recovered = sorted(set(previous) - set(current))
    for route in recovered:
        print("CMTBC source recovered: " + route, flush=True)
    temp = OUTAGE_STATE_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, OUTAGE_STATE_FILE)
    return immediate + confirmed, pending, recovered


def report_issues(issues, now=None):
    """Persist every unique source issue, but defer transient CMTBC alerts."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Source-warning timestamp must be timezone-aware")
    unique = {(issue["route"], issue["detail"]) for issue in issues}
    compact = [{"route": route, "detail": detail}
               for route, detail in sorted(unique)]
    notify_issues, pending, recovered = _filter_short_cmtbc_outages(compact, now)
    WARNINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "checked_at": now.isoformat(timespec="seconds"),
        "issues": compact,
        "duplicates_suppressed": len(issues) - len(compact),
        "pending_outages": pending, "recovered_routes": recovered,
    }
    WARNINGS_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if not notify_issues:
        # A single failed refresh is diagnostic only. Recovery clears the
        # old notification fingerprint so a later outage can alert again.
        ALERT_STATE_FILE.unlink(missing_ok=True)
        return
    notify_issues.sort(key=lambda issue: (issue["route"], issue["detail"]))
    signature = hashlib.sha256(
        json.dumps(notify_issues, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    if ALERT_STATE_FILE.exists() and ALERT_STATE_FILE.read_text().strip() == signature:
        print("Previously reported transport warning; no duplicate Telegram alert", flush=True)
        return
    message = "⚠️ Transport: требуется проверка расписания.\n" + "\n".join(
        issue["route"] + ": " + issue["detail"] for issue in notify_issues[:15])
    if len(notify_issues) > 15:
        message += "\n… и ещё {} предупреждений".format(len(notify_issues) - 15)
    try:
        if notify_telegram(message):
            ALERT_STATE_FILE.write_text(signature, encoding="utf-8")
    except Exception as exc:
        print("Failed to send Telegram alert: {}".format(exc), flush=True)


def build(data_only=False):
    data = {}
    issues = []
    try:
        for origin, destination in ROUTES:
            url = source_url(origin, destination)
            key = origin + "-" + destination
            try:
                trips, dropped = parse(fetch(url), origin, destination)
            except (requests.RequestException, ValueError) as exc:
                trips = cached_ctan_route(key)
                if trips is None:
                    # Never publish an incomplete route as a normal timetable.
                    raise RuntimeError("CMTBC {} unavailable, no safe bus/boat cache: {}".format(
                        key, exc)) from exc
                dropped = []
                message = "CMTBC sin respuesta; autobuses/barcos con datos anteriores ({})".format(
                    type(exc).__name__)
                issues.append({"route": key, "detail": message})
                print("STALE CMTBC {}: {}".format(key, exc), flush=True)
            data[key] = trips
            for trip in trips:
                # Cache fallback already generated one source-failure issue
                # for this route. Keep row-level warning visible on the site,
                # but never list it once per bus in Telegram.
                if trip["aviso"] and trip["aviso"] != CMTBC_STALE_NOTICE:
                    issues.append({"route": key, "detail": trip["aviso"]})
    except Exception as exc:
        report_issues([{"route": "ERROR", "detail": str(exc)}])
        raise
    source_problems, train_stats = replace_ctan_trains(data, date_now())
    issues.extend({"route": "Renfe", "detail": issue} for issue in source_problems)
    report_issues(issues)
    try:
        meta = apply_changes(data, notify_telegram)
    except Exception as exc:
        print("Service updates unavailable: {}".format(exc), flush=True)
        from source_alerts import apply_source_alerts
        now = date_now()
        _, verified_alerts = apply_source_alerts(data, now)
        # A source failure must never erase an independently verified strike.
        meta = {
            "date": now.date().isoformat(),
            "checked_at": now.isoformat(timespec="seconds"),
            "issues": 1, "changes": 0,
            "official_alerts": verified_alerts,
        }
    meta["renfe_schedule"] = train_stats
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
    DATA_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(
        {"data": data, "meta": meta}, ensure_ascii=False, separators=(",", ":"))
    # Atomic replace: Nginx/browser can never observe a truncated JSON response.
    temporary = DATA_OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json_text, encoding="utf-8")
    os.replace(temporary, DATA_OUTPUT)
    print("DATA", DATA_OUTPUT, len(json_text), "bytes", flush=True)
    if data_only:
        return
    output = HTML.replace("__TRANSPORT_DATA__", json.dumps(data, ensure_ascii=False).replace("<", "\\u003c"))
    output = output.replace("__SERVICE_META__", json.dumps(meta, ensure_ascii=False).replace("<", "\\u003c"))
    output = output.replace("__UPDATED__", datetime.now().strftime("%d/%m/%Y"))
    OUTPUT.write_text(output, encoding="utf-8")
    print("OUTPUT", OUTPUT, len(output), "bytes", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-only", action="store_true",
                        help="Refresh JSON data without regenerating or publishing the HTML shell")
    args = parser.parse_args()
    build(data_only=args.data_only)
