"""Daily cached Renfe static GTFS index for the three Bay of Cádiz stations.

Only public GTFS files are downloaded. The compact index is ignored by Git.
This is intentionally independent from the CMTBC timetable parser.
"""
import csv
import io
import json
import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

MADRID = ZoneInfo("Europe/Madrid")
STATIONS = {"jerez": "51300", "puerto": "51400", "cadiz": "51405"}
SOURCES = {
    "C-1": "https://ssl.renfe.com/ftransit/Fichero_CER_FOMENTO/fomento_transit.zip",
    "MD": "https://ssl.renfe.com/gtransit/Fichero_AV_LD/google_transit.zip",
}
CACHE_DIR = Path(__file__).parent / "output" / "gtfs_cache"
MAX_DOWNLOAD_BYTES = 80 * 1024 * 1024


def each_csv(zf, filename):
    with zf.open(filename) as stream:
        with io.TextIOWrapper(stream, encoding="utf-8-sig", errors="replace",
                              newline="") as handle:
            yield from csv.DictReader(handle)


def build_index_from_zip(zf):
    """Keep only trips having one of our three stations; never load the entire ZIP CSV."""
    station_ids = set(STATIONS.values())
    local = {}
    for entry in each_csv(zf, "stop_times.txt"):
        station = str(entry.get("stop_id", ""))
        if station not in station_ids:
            continue
        trip_id = entry.get("trip_id", "")
        if not trip_id:
            continue
        local.setdefault(trip_id, []).append({
            "stop_id": station,
            "seq": int(entry["stop_sequence"]) if entry.get("stop_sequence") else None,
            "arrival": entry.get("arrival_time", ""),
            "departure": entry.get("departure_time", ""),
        })

    trips = {}
    services = set()
    for entry in each_csv(zf, "trips.txt"):
        trip_id = entry.get("trip_id", "")
        if trip_id not in local:
            continue
        service = entry.get("service_id", "")
        if not service:
            continue
        stops = local[trip_id]
        if all(x["seq"] is None for x in stops):
            # Some Renfe exports omit stop_sequence. Use their GTFS scheduled
            # clocks (including 24+ hour values), not arbitrary input order.
            def gtfs_seconds(row):
                value = row.get("arrival") or row.get("departure") or ""
                try:
                    hour, minute, second = (int(p) for p in value.split(":"))
                    return hour * 3600 + minute * 60 + second
                except (ValueError, TypeError):
                    return None

            if any(gtfs_seconds(x) is None for x in stops):
                continue
            stops = sorted(stops, key=gtfs_seconds)
            if len({gtfs_seconds(x) for x in stops}) != len(stops):
                continue
            for position, item in enumerate(stops, start=1):
                item["seq"] = position
        elif any(x["seq"] is None for x in stops):
            continue
        else:
            stops = sorted(stops, key=lambda x: x["seq"])
        if len({x["stop_id"] for x in stops}) != len(stops):
            # Repeated station: stop ID alone cannot unambiguously match one event.
            continue
        trips[trip_id] = {
            "service": service,
            "route": entry.get("route_id", ""),
            "stops": stops,
        }
        services.add(service)

    calendars = {}
    if "calendar.txt" in zf.namelist():
        for entry in each_csv(zf, "calendar.txt"):
            if entry.get("service_id") in services:
                calendars[entry["service_id"]] = {
                    k: entry.get(k, "") for k in
                    ("monday", "tuesday", "wednesday", "thursday", "friday",
                     "saturday", "sunday", "start_date", "end_date")
                }

    # Only record calendar exceptions for the relevant services.
    exceptions = {}
    if "calendar_dates.txt" in zf.namelist():
        for entry in each_csv(zf, "calendar_dates.txt"):
            service = entry.get("service_id")
            if service not in services:
                continue
            exceptions.setdefault(service, {})[entry["date"]] = entry["exception_type"]

    return {"trips": trips, "calendars": calendars, "exceptions": exceptions}


def service_active(index, trip_id, day):
    """Fail closed when a trip is not established to run on that date."""
    trip = index.get("trips", {}).get(trip_id)
    if not trip:
        return False
    # Renfe MD trip IDs embed the actual service date. A previous day's delayed
    # update must never be applied to today's CTAN timetable.
    date_id = re.search(r"(\d{4}-\d{2}-\d{2})$", trip_id)
    if date_id and date_id.group(1) != day.isoformat():
        return False
    service = trip["service"]
    date_key = day.strftime("%Y%m%d")
    exception = index.get("exceptions", {}).get(service, {}).get(date_key)
    if exception is not None:
        return exception == "1"
    regular = index.get("calendars", {}).get(service)
    if not regular:
        return False
    if not regular.get("start_date", "") <= date_key <= regular.get("end_date", ""):
        return False
    return regular.get(day.strftime("%A").lower()) == "1"


def _download_zip(url, http):
    response = http.get(url, timeout=(15, 90), stream=True)
    response.raise_for_status()
    content = io.BytesIO()
    for chunk in response.iter_content(chunk_size=1024 * 1024):
        content.write(chunk)
        if content.tell() > MAX_DOWNLOAD_BYTES:
            raise ValueError("Renfe static GTFS exceeds download limit")
    content.seek(0)
    return zipfile.ZipFile(content)


def load_index(line, now, http=None, cache_dir=None):
    """One download per day; permit a <=48h cache after a transient outage.

    Return (index, warning). If no safe index is available, raise rather than
    guess. The static trip identity is always checked against CMTBC times.
    """
    now = now.astimezone(MADRID)
    cache_dir = Path(cache_dir or CACHE_DIR)
    path = cache_dir / ("cercanias.json" if line == "C-1" else "media_distancia.json")
    existing = None
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    if existing and existing.get("download_day") == now.date().isoformat():
        return existing["index"], None

    try:
        with _download_zip(SOURCES[line], http or requests) as zf:
            index = build_index_from_zip(zf)
        if not index["trips"]:
            raise ValueError("Renfe GTFS contains no local station trips")
        record = {"download_day": now.date().isoformat(), "index": index}
        cache_dir.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(json.dumps(record, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
        os.replace(temp, path)
        return index, None
    except (requests.RequestException, OSError, ValueError, KeyError,
            zipfile.BadZipFile) as exc:
        if existing:
            try:
                cached_date = datetime.strptime(existing["download_day"], "%Y-%m-%d").date()
                if 0 <= (now.date() - cached_date).days <= 2:
                    return existing["index"], "Renfe {} GTFS cache reused: {}".format(line, exc)
            except (KeyError, ValueError):
                pass
        raise RuntimeError("Renfe {} static GTFS unavailable: {}".format(line, exc)) from exc
