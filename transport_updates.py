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


def _hhmm(value):
    """Normalize GTFS HH:MM:SS and 24+ hour times to the display clock."""
    try:
        hour, minute = (int(x) for x in value.split(":")[:2])
        if hour < 0 or minute not in range(60):
            return None
        return "{:02d}:{:02d}".format(hour % 24, minute)
    except (ValueError, AttributeError, TypeError):
        return None


def _minutes(hhmm):
    parts = hhmm.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _close_clock(a, b):
    """A 1-minute rounding allowance; never use a broad nearest-train guess."""
    if a is None or b is None:
        return False
    diff = abs(_minutes(a) - _minutes(b))
    return min(diff, 1440 - diff) <= 1


def static_trip_matches(data, code, static_trip, now, trip_id):
    """Only rows generated from this exact, date-valid Renfe GTFS trip qualify.

    Old CMTBC train times may differ by 20-30 minutes. They must never be
    matched by nearest clock time, even when the real-time trip looks similar.
    """
    stops = {x["stop_id"]: x for x in static_trip["stops"]}
    result = []
    for route, trips in data.items():
        origin, destination = route.split("-")
        first = stops.get(STATIONS[origin])
        last = stops.get(STATIONS[destination])
        if not first or not last or first["seq"] >= last["seq"]:
            continue
        matches = [trip for trip in trips
                   if trip["linea"] == code and trip.get("trip_id") == trip_id
                   and trip.get("fecha_servicio") == now.date().isoformat()
                   and _close_clock(_hhmm(first["departure"]), trip["salida"])
                   and _close_clock(_hhmm(last["arrival"]), trip["llegada"])]
        if len(matches) == 1:
            result.append((route, matches[0], first, last))
    return result


def _prediction(stop_update, kind, scheduled, now):
    """Use only the actual arrival/departure field at this precise station.

    Not even a plausible delay should be silently extrapolated to another
    station. That gets a yellow 'verify' annotation rather than a green hour.
    """
    if not stop_update:
        return None
    event = stop_update.get(kind)
    if not isinstance(event, dict):
        return None
    if "time" in event:
        try:
            actual = datetime.fromtimestamp(int(event["time"]), MADRID)
            if actual.date() != now.date():
                return None
            predicted = actual.strftime("%H:%M")
            # Guard broken data such as a previous-day MD trip resurfacing today.
            if scheduled is None or min(abs(_minutes(predicted) - _minutes(scheduled)),
                                        1440 - abs(_minutes(predicted) - _minutes(scheduled))) > 180:
                return None
            return predicted
        except (OverflowError, ValueError, TypeError):
            return None
    if "delay" in event and scheduled:
        try:
            delay = int(event["delay"])
            if abs(delay) > 3 * 3600:
                return None
            mins = (_minutes(scheduled) + round(delay / 60)) % 1440
            return "{:02d}:{:02d}".format(mins // 60, mins % 60)
        except (ValueError, TypeError):
            pass
    return None


def _in_segment(updates, first, last):
    """Any update explicitly located at a station within our GTFS segment."""
    positions = {x["stop_id"]: x["seq"] for x in (first, last)}
    # For an intermediate station in the three-city subset the position will
    # be checked against the full local GTFS stop list by the caller.
    return any(str(x.get("stopId")) in positions for x in updates)


def rail_changes(data, now, session=None, statistics=None, index_loader=None):
    """Apply only date-valid, uniquely identified GTFS-RT updates to CTAN rows."""
    from renfe_static_gtfs import load_index, service_active

    events, problems = [], []
    loader = index_loader or load_index
    for code, url in RENFE.items():
        counters = {"entities": 0, "gtfs_ids": 0, "today_ids": 0,
                    "matched_trips": 0, "changes": 0, "advisories": 0}
        if statistics is not None:
            statistics[code] = counters
        try:
            feed = fetch_json(url, session)
            if not fresh_feed(feed, now):
                raise ValueError("feed timestamp is stale or in the future")
        except (ValueError, KeyError, TypeError, requests.RequestException) as exc:
            problems.append("Renfe {} RT: {}".format(code, exc))
            continue

        counters["entities"] = len(feed["entity"])
        try:
            index, cache_warning = loader(code, now)
            if cache_warning:
                problems.append(cache_warning)
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            problems.append("Renfe {} static GTFS: {}".format(code, exc))
            continue

        for entity in feed["entity"]:
            update = entity.get("tripUpdate")
            if not isinstance(update, dict):
                continue
            descriptor = update.get("trip", {})
            trip_id = str(descriptor.get("tripId") or "")
            static_trip = index.get("trips", {}).get(trip_id)
            if not static_trip:
                continue
            counters["gtfs_ids"] += 1
            start_date = descriptor.get("startDate")
            if start_date and start_date != now.strftime("%Y%m%d"):
                continue
            if not service_active(index, trip_id, now.date()):
                continue
            counters["today_ids"] += 1

            relationship = descriptor.get("scheduleRelationship", "SCHEDULED")
            if relationship not in ("SCHEDULED", "CANCELED"):
                continue

            matches = static_trip_matches(data, code, static_trip, now, trip_id)
            if not matches:
                continue
            counters["matched_trips"] += len(matches)
            updates = [x for x in update.get("stopTimeUpdate", [])
                       if isinstance(x, dict)]
            by_stop = {str(x.get("stopId")): x for x in updates if x.get("stopId")}
            local_positions = {x["stop_id"]: x["seq"] for x in static_trip["stops"]}
            for route, trip, first, last in matches:
                start = by_stop.get(first["stop_id"])
                finish = by_stop.get(last["stop_id"])
                skipped = any(
                    u and u.get("scheduleRelationship") == "SKIPPED"
                    for u in (start, finish))
                cancelled = relationship == "CANCELED" or skipped
                actual_departure = _prediction(start, "departure",
                                               _hhmm(first["departure"]), now)
                actual_arrival = _prediction(finish, "arrival",
                                             _hhmm(last["arrival"]), now)

                changed_departure = actual_departure and actual_departure != trip["salida"]
                changed_arrival = actual_arrival and actual_arrival != trip["llegada"]
                relevant = any(
                    first["seq"] <= local_positions.get(str(x.get("stopId")), -1) <= last["seq"]
                    for x in updates)
                delayed = any(
                    first["seq"] <= local_positions.get(str(x.get("stopId")), -1) <= last["seq"]
                    and abs(int(event.get("delay", 0))) >= 60
                    for x in updates
                    for event in (x.get("arrival"), x.get("departure"))
                    if isinstance(event, dict)
                )
                if cancelled:
                    status = "cancelled"
                    detail = "Renfe: servicio cancelado o parada suprimida"
                elif changed_departure or changed_arrival:
                    status = "confirmed"
                    revised_dep = actual_departure if changed_departure else trip["salida"]
                    revised_arr = actual_arrival if changed_arrival else trip["llegada"]
                    detail = "Renfe: {} → {} (previsto {} → {})".format(
                        revised_dep, revised_arr, trip["salida"], trip["llegada"])
                elif delayed and relevant:
                    status = "warning"
                    detail = "Renfe: retraso comunicado en una parada del trayecto; horario pendiente de confirmar"
                else:
                    continue

                trip.update({
                    "estado": status, "detalle": detail, "fuente_cambio": url,
                    "fecha_cambio": now.date().isoformat(), "trip_id": trip_id,
                })
                if changed_departure:
                    trip["salida_actual"] = actual_departure
                if changed_arrival:
                    trip["llegada_actual"] = actual_arrival
                counters["changes" if status != "warning" else "advisories"] += 1
                events.append({
                    "id": "rail:{}:{}:{}".format(now.date().isoformat(), route, trip_id),
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
    from maritime_status import live_maritime_changes
    ferry, ferry_problems = live_maritime_changes(data, now, session, statistics)
    if statistics.get("MARITIME_B042", {}).get("status") != "unavailable":
        bus = [event for event in bus if event.get("line") != "B-042"]
    # The maritime JSON is more authoritative for B-042 than news headlines.
    # Avoid 10 Telegram messages for the same advisory repeated in city-pair views.
    unique = {event["id"]: event for event in rail + bus + ferry}
    notify_events(list(unique.values()), sender, now)
    report = {
        "checked_at": now.isoformat(timespec="seconds"), "today": now.date().isoformat(),
        "events": list(unique.values()), "problems": rail_problems + bus_problems + ferry_problems,
        "sources": statistics,
    }
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for error in report["problems"]:
        print("Service update source: " + error, flush=True)
    return {"date": report["today"], "checked_at": report["checked_at"],
            "issues": len(report["problems"]), "changes": len(unique),
            "maritime": statistics.get("MARITIME_B042", {"status": "unknown"})}
