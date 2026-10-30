"""Passenger-first Telegram policy for Renfe GTFS realtime notifications.

The web timetable retains ALL verified per-station changes, including +/-1 min.
This module affects Telegram ONLY. Cancellations always qualify. Distinct
city-pair views of the same Renfe trip are one physical train.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")
LATE_DEPARTURE_MIN = 5
ARRIVAL_DEVIATION_MIN = 5
UNCERTAIN_INTERMEDIATE_MIN = 10
REPEAT_WORSENING_MIN = 10
REPEAT_EARLIER_DEPARTURE_MIN = 5
NAMES = {"cadiz": "Cádiz", "puerto": "El Puerto", "jerez": "Jerez"}
METRICS = ("dep_late", "dep_early", "arr_late", "arr_early", "uncertain")
ORDER = {"cancelled": 4, "skipped": 3, "timing": 2, "uncertain": 1}


def meaningful_departure(delta):
    """+1..+5 late is silent; ANY early departure matters."""
    return delta < 0 or delta > LATE_DEPARTURE_MIN


def meaningful_arrival(delta):
    return abs(delta) > ARRIVAL_DEVIATION_MIN


def build_stop_changes(origin, destination, actual_departure, actual_arrival,
                       departure_delta, arrival_delta):
    results = []
    if actual_departure and meaningful_departure(departure_delta):
        results.append({"city": origin, "kind": "Salida",
                        "time": actual_departure, "delta": departure_delta})
    if actual_arrival and meaningful_arrival(arrival_delta):
        results.append({"city": destination, "kind": "Llegada",
                        "time": actual_arrival, "delta": arrival_delta})
    return results


def _time_as_datetime(date_string, clock):
    return datetime.strptime(date_string + " " + clock, "%Y-%m-%d %H:%M").replace(
        tzinfo=MADRID)


def _still_useful(event, now):
    """No alerts for trains already finished for >15 min.

    A cross-midnight journey's arrival may occur on the following day.
    The original GTFS trip date is retained for identifying its event.
    """
    end = event["latest_end"]
    return now <= end + timedelta(minutes=15)


def merge_trips(events, now):
    """One train/day, one collection of station changes, not one per route."""
    groups = {}
    for event in events:
        identity = event["id"]
        if identity not in groups:
            groups[identity] = {**event,
                                "checks": [],
                                "segments": [],
                                "metrics": {metric: 0 for metric in METRICS}}
        group = groups[identity]
        group["segments"].append(event["segment"])
        group["latest_end"] = max(group["latest_end"], event["latest_end"])
        for field in METRICS:
            group["metrics"][field] = max(group["metrics"][field],
                                          event["metrics"].get(field, 0))
        if ORDER[event["kind"]] > ORDER[group["kind"]]:
            group["kind"] = event["kind"]
        for item in event["checks"]:
            key = (item["city"], item["kind"])
            existing = next((v for v in group["checks"]
                             if (v["city"], v["kind"]) == key), None)
            if existing is None:
                group["checks"].append(item)
            elif abs(item["delta"]) > abs(existing["delta"]):
                group["checks"].remove(existing)
                group["checks"].append(item)

    result = []
    for group in groups.values():
        if not _still_useful(group, now):
            continue
        segments = group["segments"]
        first = min(segments, key=lambda s: s["first_seq"])
        last = max(segments, key=lambda s: s["last_seq"])
        group["route"] = first["origin"] + "-" + last["destination"]
        group["departure"] = first["planned_departure"]
        group["checks"].sort(key=lambda c: (
            ["cadiz", "puerto", "jerez"].index(c["city"]) if
            c["city"] in ("cadiz", "puerto", "jerez") else 99,
            0 if c["kind"] == "Salida" else 1))
        if group["kind"] == "cancelled":
            group["detail"] = "Renfe · Tren cancelado"
        elif group["kind"] == "skipped":
            group["detail"] = "Renfe · Parada suprimida; comprobar paradas"
        elif group["kind"] == "uncertain" and not group["checks"]:
            group["detail"] = "Renfe · Retraso en el trayecto (≥10 min); horarios de estaciones por confirmar"
        else:
            notes = ["{} {} {} ({:+d} min)".format(
                item["kind"], NAMES[item["city"]], item["time"], item["delta"])
                for item in group["checks"]]
            group["detail"] = "Renfe · " + "; ".join(notes)
        group.pop("segments", None)
        group.pop("latest_end", None)
        result.append(group)
    return sorted(result, key=lambda e: (
        -ORDER[e["kind"]], e["departure"], e["id"]))


def deserves_repeat(event, previous):
    """Avoid jitter: only stronger impact or new cancellation is a new alert."""
    if not isinstance(previous, dict) or "kind" not in previous:
        return True
    kind = event["kind"]
    old_kind = previous["kind"]
    if kind in ("cancelled", "skipped"):
        return old_kind != kind
    if old_kind in ("cancelled", "skipped"):
        return False
    if kind == "timing" and old_kind == "uncertain":
        return True
    if kind == "uncertain" and old_kind == "timing":
        return False
    current = event["metrics"]
    old = previous.get("metrics", {})
    if current.get("dep_early", 0) > 0 and old.get("dep_early", 0) == 0:
        # Even a one-minute newly EARLIER departure can cause a missed train.
        return True
    return any(
        current.get(field, 0) >= old.get(field, 0) +
            (REPEAT_EARLIER_DEPARTURE_MIN if field == "dep_early"
             else REPEAT_WORSENING_MIN)
        for field in METRICS
    )


def sent_record(event, now):
    return {
        "kind": event["kind"], "metrics": event["metrics"],
        "sent_at": now.isoformat(timespec="seconds"),
    }


def format_batch(events):
    """One Telegram message per check, not a burst of individual train alerts."""
    if not events:
        raise ValueError("Cannot format an empty rail batch")
    lines = ["Cambios importantes Renfe · " + events[0]["date"]]
    for e in events:
        route = " → ".join(NAMES.get(part, part) for part in e["route"].split("-"))
        lines.append("\n• {} · {} · salida prevista {}"
                     .format(e["line"], route, e["departure"]))
        lines.append("  " + e["detail"])
    if any(e["line"] == "C-1" for e in events):
        lines.append("\nConsultar Cercanías: https://tiempo-real.renfe.com/?lang=es")
    if any(e["line"] == "MD" for e in events):
        lines.append("MD: datos oficiales de Renfe")
    return "\n".join(lines)


def batches(events, max_characters=3200):
    """Keep each Telegram send within the existing bot's 3500-character limit."""
    current = []
    for event in events:
        if current and len(format_batch(current + [event])) > max_characters:
            yield current
            current = []
        current.append(event)
    if current:
        yield current


def legacy_rail_sent(sent, event):
    """Do not re-alert every already-notified train when switching ID scheme."""
    prefix = "rail:" + event["date"] + ":"
    suffix = ":" + event["trip_id"]
    return any(key.startswith(prefix) and key.endswith(suffix)
               for key in sent if key != event["id"])
