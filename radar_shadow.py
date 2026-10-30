"""Read-only, fail-closed comparison with RadarDeTrenes station boards.

IMPORTANT: live /board-renfe payloads declare source="renfe_official".
These are a SECOND PROCESSING PATH, not independent ADIF verification.
Never overwrite passenger times, cancellations, colours or Telegram alerts.
Three inexpensive requests per normal timetable refresh (15 min).
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import re

import requests

MADRID = ZoneInfo("Europe/Madrid")
BASE = "https://radardetrenes.com/api/v1/stations/{}/board-renfe"
STATIONS = {"cadiz": "51405", "puerto": "51400", "jerez": "51300"}
EXPECTED_SOURCE = "renfe_official"
USER_AGENT = "BahiaTransportMonitor/1.0 (+https://transport.peluche-ebanache.com/)"
STALE_AFTER_SECONDS = 600
MAX_SAMPLE = 8


def _clock(epoch_ms):
    """UTC milliseconds to Europe/Madrid date and HH:MM, not naive UTC time."""
    if isinstance(epoch_ms, bool) or not isinstance(epoch_ms, (float, int)):
        raise ValueError("Invalid epoch milliseconds")
    dt = datetime.fromtimestamp(epoch_ms / 1000, MADRID)
    return dt.date().isoformat(), dt.strftime("%H:%M")


def _train_code(trip_id, service_date):
    """GTFS LD ID uses five-digit train number plus variant and ISO date."""
    match = re.fullmatch(r"(\d{5})\d" + re.escape(service_date), str(trip_id))
    return match.group(1) if match else None


def _minutes(a, b):
    diff = ((int(b[:2]) * 60 + int(b[3:])) -
            (int(a[:2]) * 60 + int(a[3:]))) % 1440
    return diff - 1440 if diff > 720 else diff


def _expected_trips(data, day):
    """Only exact MD train, stop, date and planned time (never nearest train)."""
    out = {}
    for route, entries in data.items():
        origin, destination = route.split("-")
        for trip in entries:
            if (trip.get("tipo") != "tren" or trip.get("linea") != "MD"
                    or trip.get("fecha_servicio") != day):
                continue
            train_code = _train_code(trip.get("trip_id", ""), day)
            if not train_code:
                continue
            for city, kind, planned, actual in (
                (origin, "departures", trip["salida"], trip.get("salida_actual")),
                (destination, "arrivals", trip["llegada"], trip.get("llegada_actual")),
            ):
                key = (STATIONS[city], kind, train_code, planned)
                out.setdefault(key, set()).add((trip["trip_id"], actual))
    return out


def _parse_board(payload, station, now):
    """Reject stale, unexpected, malformed or mislabeled records."""
    if not isinstance(payload, dict):
        raise ValueError("Board must be a JSON object")
    if payload.get("source") != EXPECTED_SOURCE:
        raise ValueError("Unknown board provenance: not ADIF-verified")
    _, _ = _clock(payload.get("updatedAt"))
    age = (now.astimezone(timezone.utc).timestamp() -
           payload["updatedAt"] / 1000)
    if not (-60 <= age <= STALE_AFTER_SECONDS):
        raise ValueError("Station board is stale or dated in the future")
    rows = []
    for kind in ("departures", "arrivals"):
        board = payload.get(kind)
        if not isinstance(board, list):
            raise ValueError("Missing board array " + kind)
        for item in board:
            if not isinstance(item, dict):
                continue
            if str(item.get("stationCode")) != station:
                continue
            code = item.get("trainCode")
            if not isinstance(code, str) or not re.fullmatch(r"\d{5}", code):
                continue
            # SCHEDULED is NOT an independent realtime "on time" report.
            # Only actual/estimated times may disagree with GTFS realtime.
            if item.get("timeType") not in ("ESTIMATED", "ACTUAL"):
                continue
            try:
                date, hhmm = _clock(item.get("plannedTime"))
                delay = item.get("delayMinutes")
                if isinstance(delay, bool) or not isinstance(delay, (int, float)):
                    continue
                if not (-180 <= delay <= 180):
                    continue
                # An individually old record must not be rescued by a fresh
                # board wrapper timestamp.
                row_updated = item.get("timestamp")
                if isinstance(row_updated, bool) or not isinstance(row_updated, (int, float)):
                    continue
                row_age = now.timestamp() - row_updated / 1000
                if not (-60 <= row_age <= STALE_AFTER_SECONDS):
                    continue
            except (ValueError, OverflowError, OSError):
                continue
            if date != now.date().isoformat():
                continue
            rows.append((kind, code, hhmm, round(delay)))
    return rows


def compare_station_boards(data, now, session=None):
    """Return one operator diagnostic dict, NEVER mutate data or notify.

    A match is ONLY an exact (station, train number, date, planned HH:MM).
    If the upstream train does not appear in the short board window, that is
    not evidence of cancellation or departure.
    """
    now = now.astimezone(MADRID)
    expected = _expected_trips(data, now.date().isoformat())
    result = {
        "mode": "shadow_only", "source": "renfe_official",
        "independent_adif": False,
        "provider": "RadarDeTrenes", "requested": 0, "healthy": 0,
        "matched": 0, "conflicts": 0, "unmatched": 0,
        "problems": [], "examples": [], "conflict_details": [],
        "checked_at": now.isoformat(timespec="seconds"),
    }
    if not expected:
        result["status"] = "no_today_md_trips"
        return result
    session = session or requests
    processed = set()
    for station in STATIONS.values():
        result["requested"] += 1
        try:
            response = session.get(
                BASE.format(station), timeout=6,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            response.raise_for_status()
            parsed = _parse_board(response.json(), station, now)
            result["healthy"] += 1
        except (requests.RequestException, ValueError, TypeError, KeyError,
                OverflowError, OSError) as exc:
            result["problems"].append({
                "station": station,
                "reason": type(exc).__name__,
            })
            continue
        for kind, code, planned, delay in parsed:
            key = (station, kind, code, planned)
            if key in processed:
                continue
            processed.add(key)
            if key not in expected:
                result["unmatched"] += 1
                continue
            result["matched"] += 1
            actuals = expected[key]
            if len(actuals) != 1:
                # Two trips with the same train code/time are ambiguous.
                continue
            trip_id, actual = next(iter(actuals))
            if actual is None:
                # Invalid GTFS times remain yellow, without comparing a
                # missing prediction to Radar's possibly scheduled times.
                continue
            own_delay = _minutes(planned, actual)
            if abs(own_delay - delay) > 5:
                result["conflicts"] += 1
                if len(result["examples"]) < MAX_SAMPLE:
                    result["examples"].append({
                        "station": station, "event": kind,
                        "train": code, "scheduled": planned,
                        "renfe_gtfs_delay": own_delay,
                        "radar_board_delay": delay,
                    })
                if len(result["conflict_details"]) < 20:
                    board_minutes = (int(planned[:2]) * 60 +
                                     int(planned[3:]) + delay) % 1440
                    result["conflict_details"].append({
                        "trip_id": trip_id, "station": station,
                        "city": next(city for city, code in STATIONS.items()
                                     if code == station),
                        "event": kind, "scheduled": planned,
                        "gtfs_time": actual,
                        "radar_time": "{:02d}:{:02d}".format(
                            board_minutes // 60, board_minutes % 60),
                        "difference_minutes": abs(own_delay - delay),
                        "secondary_source": "RadarDeTrenes (datos Renfe)",
                        "independent_adif": False,
                    })
    result["status"] = (
        "available" if result["healthy"] == len(STATIONS)
        else "partial" if result["healthy"] else "unavailable"
    )
    return result
