#!/usr/bin/env python3
"""Public, read-only Renfe feed diagnostic; never logs credentials."""
import collections
import datetime
import json
import urllib.request

SOURCES = {
    "C-1": "https://gtfsrt.renfe.com/trip_updates.json",
    "MD": "https://gtfsrt.renfe.com/trip_updates_LD.json",
}
STATIONS = {"Jerez": "51300", "El Puerto": "51400", "Cadiz": "51405"}
for name, url in SOURCES.items():
    print("\n===", name, "===")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TransportDiagnose/1.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            feed = json.load(response)
        print("timestamp",feed["header"].get("timestamp"))
        entities = feed["entity"]
        print("entities",len(entities))
        print("updates_per_entity",collections.Counter(
            len(e.get("tripUpdate", {}).get("stopTimeUpdate", [])) for e in entities).most_common(10))
        stops = collections.Counter(str(s.get("stopId")) for e in entities for s in
            e.get("tripUpdate", {}).get("stopTimeUpdate", []))
        print("target station occurrences:",{name:stops.get(code,0) for name,code in STATIONS.items()})
        print("top station IDs", stops.most_common(14))
        examples = []
        for entity in entities:
            update = entity.get("tripUpdate", {})
            for stop in update.get("stopTimeUpdate", []):
                if str(stop.get("stopId")) in STATIONS.values():
                    examples.append({
                        "trip": update.get("trip", {}),
                        "id": stop.get("stopId"),
                        "event": stop.get("departure") or stop.get("arrival"),
                        "stop_count":len(update.get("stopTimeUpdate",[]))
                    })
            if len(examples) >= 3: break
        print("matching-station examples", json.dumps(examples[:3]))
        print("first entry",json.dumps(entities[:1])[:900])
    except Exception as e:
        print("FEED ERROR",repr(e))
