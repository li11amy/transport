#!/usr/bin/env python3
"""Remove impossible arrivals from existing published JSON immediately.

The full Renfe GTFS realtime parser now rejects these. This helper updates
an already-published shared JSON without a full external refetch; scheduled
15-minute refreshes will then keep it clean. Cancellation rows are untouched.
"""
import argparse
import json
import os
import tempfile
from pathlib import Path
from transport_updates import plausible_segment_arrival, _passenger_rail_times


def sanitize(payload):
    if not isinstance(payload.get("data"), dict):
        raise ValueError("Missing schedule data")
    changed = []
    for route, trips in payload["data"].items():
        for item in trips:
            if item.get("tipo") != "tren" or item.get("estado") == "cancelled":
                continue
            actual_arr = item.get("llegada_actual")
            if not actual_arr:
                continue
            if plausible_segment_arrival(item["salida"], item["llegada"],
                                         item.get("salida_actual"), actual_arr):
                continue
            previous = actual_arr
            item.pop("llegada_actual", None)
            # A valid confirmed departure update may still be shown, but an
            # impossible arrival cannot be called confirmed.
            changed_departure = (item.get("salida_actual") and
                                 item["salida_actual"] != item["salida"])
            if changed_departure:
                item["estado"] = "confirmed"
                item["detalle"] = (
                    _passenger_rail_times(
                        item["salida"], item["llegada"],
                        item["salida_actual"], None)
                    + " · Llegada sin confirmar (predicción incoherente)")
            else:
                item["estado"] = "warning"
                item["detalle"] = (
                    "Renfe: predicción de llegada incoherente; "
                    "horario pendiente de confirmar")
            changed.append((route, item.get("trip_id", ""), previous))
    return changed


def save_atomically(path, payload):
    path = Path(path)
    fd, temp = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(payload, out, ensure_ascii=False, separators=(",",":"))
            out.write("\n")
        os.chmod(temp,0o644)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--path", default="/srv/www/transport/transport_data.json")
    opts=parser.parse_args()
    path=Path(opts.path)
    payload=json.loads(path.read_text(encoding="utf-8"))
    today=payload.get("meta",{}).get("date","")
    if not today or len(payload.get("data",{})) != 6:
        raise ValueError("Refusing to modify incomplete timetable")
    changed=sanitize(payload)
    print("Impossible arrival forecasts:",len(changed))
    for route, trip, actual in changed[:15]:
        print(route,trip,"invalid arrival",actual)
    if opts.apply and changed:
        save_atomically(path,payload)
        print("Published shared JSON sanitized; no fabricated arrival times")
    elif not opts.apply:
        print("Dry run only (pass --apply after validation)")


if __name__=="__main__":
    main()
