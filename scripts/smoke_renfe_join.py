#!/usr/bin/env python3
"""Network-only smoke test of official Renfe static/live joins; no production writes.

Downloads public feeds and writes only to an ephemeral temporary cache.
Does not send Telegram messages, commit, or change Nginx/systemd.
"""
import json
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

from renfe_static_gtfs import load_index, service_active
from transport_updates import RENFE, fetch_json, fresh_feed, static_trip_matches

now = datetime.now(ZoneInfo("Europe/Madrid"))
try:
    from build_horarios import ROUTES, source_url, fetch, parse
    ctan = {a + "-" + b: parse(fetch(source_url(a, b)), a, b)[0]
            for a, b in ROUTES}
    print("CTAN rows:", {key: len(rows) for key, rows in ctan.items()}, flush=True)
except Exception as exc:
    print("CTAN site unavailable in CI:", str(exc), flush=True)
    ctan = {}
with tempfile.TemporaryDirectory() as directory:
    for line, url in RENFE.items():
        index, warning = load_index(line, now, cache_dir=directory)
        feed = fetch_json(url)
        join = []
        for entity in feed["entity"]:
            desc = entity.get("tripUpdate", {}).get("trip", {})
            tid = str(desc.get("tripId", ""))
            if tid in index["trips"]:
                join.append(tid)
        current = [tid for tid in join if service_active(index, tid, now.date())]
        print("SAMPLE ACTIVE CALENDARS:", json.dumps([{
            "trip_id": tid,
            "service": index["trips"][tid]["service"],
            "calendar": index["calendars"].get(index["trips"][tid]["service"]),
            "exception_today": index["exceptions"].get(
                index["trips"][tid]["service"], {}).get(now.strftime("%Y%m%d")),
        } for tid in join[:4]], ensure_ascii=False), flush=True)
        print(json.dumps({
            "line": line,
            "fresh": fresh_feed(feed, now),
            "static_local_trips": len(index["trips"]),
            "realtime_entities": len(feed["entity"]),
            "joined_by_trip_id": len(join),
            "active_today": len(current),
            "ctan_matched_today": sum(
                len(static_trip_matches(ctan, line, index["trips"][tid], now))
                for tid in current),
            "warning": warning,
        }, ensure_ascii=False), flush=True)
        if not index["trips"] or not join:
            raise RuntimeError(line + ": no GTFS ID matches; check the source format")
