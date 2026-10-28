#!/usr/bin/env python3
"""Read-only inspection of Renfe's static GTFS and today's GTFS-RT trip IDs.

This command downloads public ZIPs temporarily, prints only non-secret metadata,
does not modify the running website or use the production output directory.
"""
import csv
import io
import json
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

STATIONS = {"51300": "Jerez", "51400": "El Puerto", "51405": "Cadiz"}
FEEDS = {
    "C-1": (
        "https://ssl.renfe.com/ftransit/Fichero_CER_FOMENTO/fomento_transit.zip",
        "https://gtfsrt.renfe.com/trip_updates.json",
    ),
    "MD": (
        "https://ssl.renfe.com/gtransit/Fichero_AV_LD/google_transit.zip",
        "https://gtfsrt.renfe.com/trip_updates_LD.json",
    ),
}
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "BahiaTransportDiagnostic/1.0"


def read_csv(zf, filename):
    with zf.open(filename) as stream:
        with io.TextIOWrapper(stream, encoding="utf-8-sig", errors="replace", newline="") as text:
            yield from csv.DictReader(text)


def fetch_json(url):
    error = None
    for attempt in range(3):
        try:
            response = SESSION.get(url, timeout=(15, 45))
            response.raise_for_status()
            data = response.json()
            if isinstance(data.get("entity"), list):
                return data
        except (requests.RequestException, ValueError) as exc:
            error = exc
    print("Realtime feed error after 3 attempts:", repr(error))
    return {"entity": []}


def fetch_zip(url):
    with SESSION.get(url, timeout=(15, 120), stream=True) as resp:
        resp.raise_for_status()
        downloaded = io.BytesIO()
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            downloaded.write(chunk)
            if downloaded.tell() > 160 * 1024 * 1024:
                raise ValueError("GTFS ZIP exceeds 160 MiB safety limit")
        print("Static GTFS downloaded:", downloaded.tell(), "bytes")
        downloaded.seek(0)
        return zipfile.ZipFile(downloaded)


def fold(value):
    return "".join(c for c in unicodedata.normalize("NFKD", str(value).lower())
                   if not unicodedata.combining(c))


def candidate_station(name):
    n = fold(name)
    return "cadiz" in n or "jerez" in n or "puerto de santa" in n or "puerto de sta" in n


def inspect(label, static_url, rt_url):
    print("\n=====", label, "=====")
    rt = fetch_json(rt_url)
    print("RT entities:", len(rt.get("entity", [])), "timestamp:", rt.get("header", {}).get("timestamp"))
    rt_trips = {}
    for e in rt["entity"]:
        update = e.get("tripUpdate", {})
        desc = update.get("trip", {})
        trip_id = desc.get("tripId")
        if trip_id:
            rt_trips[str(trip_id)] = update
    print("RT IDs (first 5):", list(rt_trips)[:5])
    print("RT stop counts:", Counter(
        len(t.get("stopTimeUpdate", [])) for t in rt_trips.values()).most_common(5))
    local_rt = [
        (trip_id, u) for trip_id, u in rt_trips.items()
        if any(str(s.get("stopId")) in STATIONS for s in u.get("stopTimeUpdate", []))
    ]
    print("RT with local station:", len(local_rt))
    for trip_id, update in local_rt[:6]:
        print("  RT local:", trip_id, "stops:",
              [(s.get("stopId"), s.get("arrival"), s.get("departure"))
               for s in update.get("stopTimeUpdate", [])])

    try:
        with fetch_zip(static_url) as zf:
            names = zf.namelist()
            print("ZIP files:", names[:15])
            stop_candidates = {str(s["stop_id"]): s.get("stop_name", "") for s in
                               read_csv(zf, "stops.txt")
                               if candidate_station(s.get("stop_name", "")) or
                                  str(s.get("stop_id")) in STATIONS}
            print("Potential local GTFS stops:", stop_candidates)
            train_ids = {}
            matched_rt = []
            for t in read_csv(zf, "trips.txt"):
                tid = str(t.get("trip_id", ""))
                if tid in rt_trips:
                    matched_rt.append(tid)
                train_ids[tid] = (t.get("route_id"), t.get("service_id"))
            print("Static trip count:", len(train_ids))
            print("Exact RT tripId matches:", len(matched_rt))
            print("Exact local RT tripId matches:",
                  [x[0] for x in local_rt if x[0] in train_ids][:12])
            print("Example static trip IDs:", list(train_ids)[:6])
            print("Recent train ID 1303512026-10-27 in static:",
                  train_ids.get("1303512026-10-27"))
            local_trip_times = defaultdict(list)
            for row in read_csv(zf, "stop_times.txt"):
                sid = str(row.get("stop_id", ""))
                if sid in stop_candidates and row.get("trip_id") in train_ids:
                    local_trip_times[row["trip_id"]].append(
                        (sid, row.get("arrival_time"), row.get("departure_time")))
            print("Static trips through local stops:", len(local_trip_times))
            for trip_id, update in local_rt[:6]:
                print("  Joined", trip_id, "route/service:", train_ids.get(trip_id),
                      "local GTFS stop times:", local_trip_times.get(trip_id))
            print("Static local sample:",
                  [(tid, train_ids[tid], rows) for tid, rows in list(local_trip_times.items())[:4]])
    except (requests.RequestException, OSError, ValueError, zipfile.BadZipFile, KeyError) as exc:
        print("Static GTFS error:", repr(exc))


if __name__ == "__main__":
    for name, (static, realtime) in FEEDS.items():
        inspect(name, static, realtime)
