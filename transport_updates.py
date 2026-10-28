"""Conservative, date-scoped service changes for the Bahía de Cádiz timetable.

Only a uniquely matched Renfe GTFS-RT trip may change a displayed train time.
Bus announcements are advisory; they never overwrite scheduled departures.
"""
import hashlib
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, parse_qs, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

MADRID = ZoneInfo("Europe/Madrid")
RENFE = {
    "C-1": "https://gtfsrt.renfe.com/trip_updates.json",
    "MD": "https://gtfsrt.renfe.com/trip_updates_LD.json",
}
STATIONS = {"jerez": "51300", "puerto": "51400", "cadiz": "51405"}
STATION_NAMES = {
    "jerez": "Estación de Jerez",
    "puerto": "Estación FC",
    "cadiz": "Plaza de Sevilla-Estación de Cádiz",
}
BUS_LINES_URL = "https://siu.cmtbc.es/es/movil/lineas.php"
BUS_NOTICE_URL = "https://siu.cmtbc.es/es/movil/noticias.php?linea={}"
NOTICE_WORDS = re.compile(
    r"horari|servicio|servicios|suspend|suprim|cancel|incidenc|corte|"
    r"parada|huelga|refuerz|desvi|especial|interrump|modific|alteraci", re.I)
NON_SERVICE_WORDS = re.compile(
    r"tarifa|abono|tarjeta|precios|bonificaci|movilidad personal", re.I)
DATE_TITLE = re.compile(r"^\s*(\d{2}/\d{2}/\d{4})\s+(.+?)\s*$")
STATE_FILE = Path(__file__).parent / "output" / "service_change_notifications.json"
REPORT_FILE = Path(__file__).parent / "output" / "service_change_report.json"


def date_now(now=None):
    return (now or datetime.now(MADRID)).astimezone(MADRID)


def runs_today(code, now):
    """Only normal weekly rules; unverified calendars must not be auto-matched."""
    weekday = now.weekday()
    return {
        "L-J": weekday < 4,
        "L-V": weekday < 5,
        "L-S": weekday < 6,
        "L-D": True,
        "S": weekday == 5,
        "D": weekday == 6,
        "S-D-F": weekday >= 5,
        "V": weekday == 4,
    }.get(code, False)


def fetch_json(url, session=None):
    response = (session or requests).get(url, timeout=15)
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict) or not isinstance(result.get("entity"), list):
        raise ValueError("unexpected GTFS-RT JSON structure")
    return result


def fresh_feed(feed, now):
    stamp = int(feed["header"]["timestamp"])
    return abs(now.timestamp() - stamp) <= 600


def stop_event(stop_update, preferred):
    event = stop_update.get(preferred) or stop_update.get("arrival" if preferred == "departure" else "departure") or {}
    if not isinstance(event, dict) or "time" not in event:
        return None
    actual_epoch = int(event["time"])
    delay = int(event.get("delay", 0))
    return actual_epoch - delay, actual_epoch


def local_hhmm(epoch):
    return datetime.fromtimestamp(epoch, MADRID).strftime("%H:%M")


def local_day(epoch):
    return datetime.fromtimestamp(epoch, MADRID).date()


def unique_matching_trip(data, code, stops, now):
    """Require both station stop updates, not a guessed train number or direction.

    A CTAN row has no Renfe trip_id. Matching only an origin clock time could
    attribute the update to another train, so ambiguous updates stay untouched.
    """
    candidates = []
    for route, trips in data.items():
        origin, destination = route.split("-")
        first = stops.get(STATIONS[origin])
        last = stops.get(STATIONS[destination])
        if not first or not last:
            continue
        dep, arr = stop_event(first, "departure"), stop_event(last, "arrival")
        if not dep or not arr or local_day(dep[0]) != now.date() or local_day(arr[0]) != now.date():
            continue
        for trip in trips:
            if trip["linea"] != code or not runs_today(trip["dias"], now):
                continue
            if local_hhmm(dep[0]) != trip["salida"] or local_hhmm(arr[0]) != trip["llegada"]:
                continue
            candidates.append((route, trip, dep, arr, first, last))
    # Multiple city-pair views of the same physical train are allowed.
    # Multiple trips in the same pair with identical schedule are not.
    if len({route for route, *_ in candidates}) != len(candidates):
        return []
    return candidates


def rail_changes(data, now, session=None, statistics=None):
    events, problems = [], []
    for code, url in RENFE.items():
        counters = {"entities": 0, "station_pairs": 0, "matched_trips": 0, "changes": 0}
        if statistics is not None:
            statistics[code] = counters
        try:
            feed = fetch_json(url, session)
            if not fresh_feed(feed, now):
                raise ValueError("feed timestamp is stale or in the future")
        except (ValueError, KeyError, TypeError, requests.RequestException) as exc:
            problems.append("Renfe {}: {}".format(code, exc))
            continue
        counters["entities"] = len(feed["entity"])
        for entity in feed["entity"]:
            update = entity.get("tripUpdate")
            if not isinstance(update, dict):
                continue
            descriptor = update.get("trip", {})
            relationship = descriptor.get("scheduleRelationship", "SCHEDULED")
            # Cancellations without stop events cannot be safely tied to a CTAN row.
            stops = {
                str(x.get("stopId")): x
                for x in update.get("stopTimeUpdate", [])
                if isinstance(x, dict) and str(x.get("stopId")) in STATIONS.values()
            }
            if len(stops) < 2:
                continue
            counters["station_pairs"] += 1
            matched = unique_matching_trip(data, code, stops, now)
            counters["matched_trips"] += len(matched)
            for route, trip, departure, arrival, first, last in matched:
                source_id = str(descriptor.get("tripId") or entity.get("id"))
                skipped = any(
                    x.get("scheduleRelationship") == "SKIPPED" for x in (first, last))
                cancelled = relationship == "CANCELED" or skipped
                new_departure, new_arrival = local_hhmm(departure[1]), local_hhmm(arrival[1])
                if not cancelled and new_departure == trip["salida"] and new_arrival == trip["llegada"]:
                    continue
                status = "cancelled" if cancelled else "confirmed"
                detail = (
                    "Renfe: servicio cancelado o parada suprimida"
                    if cancelled else
                    "Renfe: {} → {} (previsto {} → {})".format(
                        new_departure, new_arrival, trip["salida"], trip["llegada"]))
                trip.update({
                    "estado": status, "detalle": detail, "fuente_cambio": url,
                    "fecha_cambio": now.date().isoformat(),
                    "trip_id": source_id,
                })
                if not cancelled:
                    trip["salida_actual"] = new_departure
                    trip["llegada_actual"] = new_arrival
                counters["changes"] += 1
                events.append({
                    "id": "rail:{}:{}:{}:{}:{}".format(
                        now.date().isoformat(), route, code, trip["salida"], trip["dias"]),
                    "route": route, "line": code, "detail": detail, "source": url,
                    "date": now.date().isoformat(),
                })
    return events, problems


def bus_notices(data, now, session=None, statistics=None):
    """Parse line-specific public notices; never infer exact cancelled departures."""
    events, problems = [], []
    counters = {"lines": 0, "identified": 0, "notices": 0, "warning_lines": 0}
    if statistics is not None:
        statistics["CMTBC"] = counters
    http = session or requests
    bus_codes = sorted({trip["linea"] for trips in data.values()
                        for trip in trips if trip["tipo"] in ("bus", "catamaran")})
    counters["lines"] = len(bus_codes)
    try:
        response = http.get(BUS_LINES_URL, timeout=15)
        response.raise_for_status()
        index = BeautifulSoup(response.text, "html.parser")
        ids = {}
        for a in index.select("a[href]"):
            match = re.search(r"\b([MB]-\d{3})\b", a.get_text(" ", strip=True))
            if not match:
                continue
            line_id = parse_qs(urlparse(a["href"]).query).get("linea", [None])[0]
            if line_id and line_id.isdecimal():
                ids[match.group(1)] = line_id
    except requests.RequestException as exc:
        return events, ["CMTBC list: {}".format(exc)]
    counters["identified"] = sum(code in ids for code in bus_codes)
    for code in bus_codes:
        if code not in ids:
            problems.append("CMTBC: no line ID for {}".format(code))
            continue
        url = BUS_NOTICE_URL.format(ids[code])
        try:
            response = http.get(url, timeout=12)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as exc:
            problems.append("CMTBC {}: {}".format(code, exc))
            continue
        notices = []
        for a in soup.select("a[href]"):
            match = DATE_TITLE.match(a.get_text(" ", strip=True))
            if not match:
                continue
            published = datetime.strptime(match.group(1), "%d/%m/%Y").date()
            title = match.group(2)
            if not (now.date() - timedelta(days=14) <= published <= now.date()):
                continue
            if not NOTICE_WORDS.search(title) or NON_SERVICE_WORDS.search(title):
                continue
            notices.append((published, title, urljoin(url, a["href"])))
        counters["notices"] += len(notices)
        if not notices:
            continue
        notices.sort(reverse=True)
        published, title, source = notices[0]
        affected_routes = []
        for route, trips in data.items():
            for trip in trips:
                if trip["linea"] != code or not runs_today(trip["dias"], now):
                    continue
                trip.update({
                    "estado": "warning",
                    "detalle": "Aviso del Consorcio: " + title,
                    "fuente_cambio": source,
                    "fecha_cambio": now.date().isoformat(),
                })
                affected_routes.append(route)
        if affected_routes:
            counters["warning_lines"] += 1
            events.append({
                "id": "bus:{}:{}".format(code, published.isoformat()),
                "route": ", ".join(sorted(set(affected_routes))),
                "line": code, "detail": title, "source": source,
                "date": now.date().isoformat(),
            })
    return events, problems


def notify_events(events, sender, now):
    """One notification per new/change event. Failed sends are retried on next run."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if not isinstance(state.get("sent"), dict):
        state = {"sent": {}}
    sent = state["sent"]
    for event in events:
        # The publication date of a persistent bus notice is NOT a new event.
        # Only its ID, detail and source determine whether to send again.
        signature = {k: v for k, v in event.items() if k != "date"}
        digest = hashlib.sha256(
            json.dumps(signature, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if sent.get(event["id"]) == digest:
            continue
        message = (
            "Cambio de transporte · {}\n{} · {}\n{}\nFuente: {}".format(
                event["date"], event["route"], event["line"],
                event["detail"], event["source"]))
        try:
            if sender(message):
                sent[event["id"]] = digest
        except Exception as exc:
            print("Transport change alert failed: {}".format(exc), flush=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_changes(data, sender, now=None, session=None):
    now = date_now(now)
    statistics = {}
    rail, rail_problems = rail_changes(data, now, session, statistics)
    bus, bus_problems = bus_notices(data, now, session, statistics)
    # Avoid 10 Telegram messages for the same advisory repeated in city-pair views.
    unique = {event["id"]: event for event in rail + bus}
    notify_events(list(unique.values()), sender, now)
    report = {
        "checked_at": now.isoformat(timespec="seconds"), "today": now.date().isoformat(),
        "events": list(unique.values()), "problems": rail_problems + bus_problems,
        "sources": statistics,
    }
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for error in report["problems"]:
        print("Service update source: " + error, flush=True)
    return {"date": report["today"], "checked_at": report["checked_at"],
            "issues": len(report["problems"]), "changes": len(unique)}
