"""Conservative live B-042 ferry disruptions from the official CMTBC JSON API.

Do NOT assume a whole line is cancelled when the authority lists only a few
departures. Unknown scopes are warnings, never invented red cancellations.
"""
import json
import re
import unicodedata
from datetime import datetime
from html import unescape
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

MADRID = ZoneInfo("Europe/Madrid")
STATUS_URL = "https://cmtbc.es/api/v2/web/estadomaritimo"
PUBLIC_URL = "https://cmtbc.es/?op=maritimo"
FERRY = "B-042"
CLOCK = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b")
ORIGIN = re.compile(
    r"\bsalidas?\s+desde\s+(cadiz|el puerto)\b(?:[^\n:]{0,65})\s*:?",
    re.I,
)


def fold(value):
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", value.lower())
        if not unicodedata.combining(ch))


def parse_local_datetime(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip()).replace(tzinfo=MADRID)
    except ValueError:
        return None


def cancelled_departures(raw):
    """Read specifically named boat departures, excluding substitute bus times.

    Return route -> exact HH:MM departures. If a notice doesn't state boat
    departure direction and time clearly, return empty and warn instead.
    """
    text = BeautifulSoup(unescape(str(raw or "")), "html.parser").get_text("\n", strip=True)
    norm = fold(text)
    norm = re.split(
        r"\bservicios?\s+alternativos?\b|\bautobuses?\s+alternativos?\b|"
        r"\bel resto de los servicios\b", norm, maxsplit=1)[0]
    found = {}
    markers = list(ORIGIN.finditer(norm))
    for i, match in enumerate(markers):
        origin = match.group(1)
        key = "cadiz-puerto" if origin == "cadiz" else "puerto-cadiz"
        end = markers[i + 1].start() if i + 1 < len(markers) else len(norm)
        span = norm[match.end():end]
        # Stop at explanatory paragraphs, not arbitrary times later on the page.
        span = re.split(r"\n\s*\n|(?:\bdesde\b|\bhasta\b)\s+\d{4}-\d{2}-\d{2}", span, maxsplit=1)[0]
        hours = CLOCK.findall(span)
        if hours:
            found.setdefault(key, set()).update(h.zfill(5) for h in hours)
    return found


def _effective_now(window, now):
    start = parse_local_datetime(window.get("fecha_inicio"))
    end = parse_local_datetime(window.get("fecha_fin"))
    if not start:
        return False
    return start <= now <= (end or now)


def _covers_departure(window, day, hhmm):
    start = parse_local_datetime(window.get("fecha_inicio"))
    end = parse_local_datetime(window.get("fecha_fin"))
    if not start:
        return False
    departure = datetime.fromisoformat(day.isoformat() + "T" + hhmm).replace(tzinfo=MADRID)
    return start <= departure <= (end or departure)


def evaluate_status(data, now, payload):
    """Mutate only today's boat rows. Return (event, diagnostics) for Telegram."""
    if not isinstance(payload, dict):
        raise ValueError("maritime response is not an object")
    observed = parse_local_datetime(payload.get("fecha_consulta"))
    if not observed or abs((now - observed).total_seconds()) > 20 * 60:
        raise ValueError("maritime response timestamp absent or stale")
    line = payload.get("lineas", {}).get(FERRY)
    if not isinstance(line, dict) or not isinstance(line.get("suspendida"), bool):
        raise ValueError("B-042 has no usable status")
    windows = []
    active = line.get("suspension")
    upcoming = line.get("proxima")
    if line["suspendida"] and not isinstance(active, dict):
        raise ValueError("B-042 suspended but details absent")
    if line["suspendida"]:
        windows.append(("active", active))
    if isinstance(upcoming, dict):
        windows.append(("scheduled", upcoming))

    status = {"operational": not line["suspendida"],
              "checked_at": observed.isoformat(timespec="seconds"),
              "red": 0, "yellow": 0, "source": PUBLIC_URL}
    changes = []
    status["messages"] = []
    # A fresh operational maritime status outranks an old headline-only warning.
    for route, trips in data.items():
        if route not in ("cadiz-puerto", "puerto-cadiz"):
            continue
        for trip in trips:
            if trip.get("linea") == FERRY and trip.get("estado") == "warning" and _runs_today(trip.get("dias"), now):
                trip.pop("estado", None)
                trip.pop("detalle", None)
                trip.pop("fuente_cambio", None)
                trip.pop("fecha_cambio", None)
    for kind, window in windows:
        if not isinstance(window, dict):
            continue
        text = str(window.get("texto") or "")
        departure_times = cancelled_departures(text)
        all_cancelled = bool(re.search(
            r"\b(?:todos los servicios|todas las salidas|suspension total|"
            r"servicio suspendido por completo)\b", fold(text)))
        reason = window.get("causa") or "Suspensión del servicio marítimo"
        note = BeautifulSoup(unescape(text), "html.parser").get_text(" ", strip=True)
        status["messages"].append(str(reason) + (": " + note[:380] if note else ""))
        for route, trips in data.items():
            if route not in ("cadiz-puerto", "puerto-cadiz"):
                continue
            for trip in trips:
                if trip.get("linea") != FERRY or not _runs_today(trip.get("dias"), now):
                    continue
                if not _covers_departure(window, now.date(), trip["salida"]):
                    continue
                definite = trip["salida"] in departure_times.get(route, set()) or all_cancelled
                # When a notice specifies other individual departures, do not
                # mark the remaining trips as cancelled or uncertain.
                if departure_times and not definite:
                    continue
                level = "cancelled" if definite else "warning"
                trip.update({
                    "estado": level,
                    "detalle": ("Catamarán cancelado. " if definite else
                               "Posible alteración del catamarán. ") + str(reason),
                    "fuente_cambio": PUBLIC_URL,
                    "fecha_cambio": now.date().isoformat(),
                })
                status["red" if definite else "yellow"] += 1
                changes.append((route, trip["salida"], level))
    return changes, status


def _runs_today(code, now):
    weekday = now.weekday()
    return {
        "L-J": weekday <= 3, "L-V": weekday <= 4,
        "L-S": weekday <= 5, "L-D": True,
        "S": weekday == 5, "D": weekday == 6,
        "S-D-F": weekday >= 5, "V": weekday == 4,
    }.get(code, False)


def live_maritime_changes(data, now, session=None, statistics=None):
    """Return alerts and source errors. On outage, mark boat as unverified."""
    http = session or requests
    diagnostics = {"status": "unknown", "red": 0, "yellow": 0}
    if statistics is not None:
        statistics["MARITIME_B042"] = diagnostics
    errors, events = [], []
    try:
        response = http.get(STATUS_URL, timeout=12)
        response.raise_for_status()
        # CMTBC returns JSON prefixed with a UTF-8 BOM on the live VPS.
        # requests.Response.json() rejects it in some environments.
        payload = json.loads(response.content.decode("utf-8-sig"))
        changes, result = evaluate_status(data, now, payload)
        diagnostics.update(result)
        diagnostics["status"] = "affected" if changes else "operational"
        if changes:
            # One Telegram alert for the whole maritime disruption, not each row.
            summary = ", ".join(
                "{} {} ({})".format(route.replace("-", " → "), dep,
                                    "cancelado" if level == "cancelled" else "revisar")
                for route, dep, level in sorted(set(changes)))
            reason = "; ".join(result.get("messages", []))
            events.append({
                "id": "maritime:{}:{}".format(FERRY, now.date().isoformat()),
                "date": now.date().isoformat(), "route": "Cádiz ↔ El Puerto",
                "line": FERRY,
                "detail": summary + ("\n" + reason if reason else ""),
                "source": PUBLIC_URL,
            })
        return events, errors
    except (requests.RequestException, ValueError, TypeError, AttributeError, KeyError) as exc:
        errors.append("CMTBC maritime API: {}".format(exc))
        diagnostics["status"] = "unavailable"
        for route, trips in data.items():
            if route not in ("cadiz-puerto", "puerto-cadiz"):
                continue
            for trip in trips:
                if trip.get("linea") != FERRY or not _runs_today(trip.get("dias"), now):
                    continue
                # Do not downgrade a confirmed cancellation from a separate
                # trustworthy source to yellow just because this API failed.
                if trip.get("estado") == "cancelled":
                    continue
                trip.update({
                    "estado": "warning",
                    "detalle": "No se ha podido comprobar el estado del catamarán",
                    "fuente_cambio": PUBLIC_URL,
                    "fecha_cambio": now.date().isoformat(),
                })
                diagnostics["yellow"] += 1
        events.append({
            "id": "maritime:unavailable:{}".format(now.date().isoformat()),
            "date": now.date().isoformat(), "route": "Cádiz ↔ El Puerto",
            "line": FERRY,
            "detail": "No se ha podido comprobar el estado del catamarán B-042",
            "source": PUBLIC_URL,
        })
        return events, errors
