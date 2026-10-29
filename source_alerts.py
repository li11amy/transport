"""Source-backed, date-limited transport advisories for events outside GTFS-RT.

A strike announcement does NOT establish that any individual train is
cancelled. Explicit cancellations from Renfe GTFS-RT retain higher priority.
This file is updated only when an official source has been independently
verified; it is never inferred from absence of realtime entities.
"""
import json
from datetime import datetime
from pathlib import Path

ALERTS_FILE = Path(__file__).parent / "service_alerts.json"


def load_alerts(path=ALERTS_FILE):
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("alerts"), list):
        raise ValueError("Invalid official advisory configuration")
    return document["alerts"]


def apply_source_alerts(data, now, alerts=None):
    """Annotate only exact-date Renfe trains; return deduplicated Telegram events.

    Does not alter bus/ferry trips, marked cancellations or actual times.
    """
    if alerts is None:
        alerts = load_alerts()
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("Advisory date must be timezone aware")
    day = now.date().isoformat()
    events = []
    summary = []
    for alert in alerts:
        if not isinstance(alert, dict) or alert.get("date") != day:
            continue
        if alert.get("type") != "rail_strike" or alert.get("verified") is not True:
            continue
        source = alert.get("source", "")
        message = alert.get("description", "")
        if not source.startswith("https://") or not message or not alert.get("id"):
            raise ValueError("Alert without official source, ID or message")
        affected = 0
        for trips in data.values():
            for trip in trips:
                if trip.get("tipo") != "tren" or trip.get("linea") not in alert.get("lines", []):
                    continue
                if trip.get("fecha_servicio") != day:
                    continue
                if trip.get("estado") == "cancelled":
                    # Already specifically cancelled by Renfe GTFS Realtime.
                    continue
                affected += 1
                previous = trip.get("detalle") or ""
                if trip.get("estado") != "confirmed":
                    trip["estado"] = "warning"
                trip["detalle"] = (previous + " · " if previous else "") + message
                trip["aviso"] = message
                trip["fuente_cambio"] = source
                trip["fecha_cambio"] = day
        if affected:
            summary.append({
                "id": alert["id"], "date": day, "title": alert.get("title", "Aviso Renfe"),
                "source": source, "affected_rows": affected,
            })
            events.append({
                "id": "official-alert:" + alert["id"],
                "date": day,
                "route": "Cádiz · El Puerto · Jerez",
                "line": "C-1 / MD",
                "detail": alert.get("title", "Aviso Renfe") + "\n" + message,
                "source": source,
            })
    return events, summary
