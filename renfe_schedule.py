"""Produce train timetables from Renfe's official dated GTFS instead of stale CMTBC.

The four existing UI tabs represent the next available dates for each weekday
group. Every train includes its exact underlying GTFS service date and trip_id.
Bus and boat schedules continue to originate from the CMTBC tables.
"""
from datetime import timedelta

from renfe_static_gtfs import STATIONS, SOURCES, load_index, service_active
from transport_updates import MADRID, _hhmm

STATION_LABELS = {
    "jerez": "Estación de Jerez",
    "puerto": "Estación FC",
    "cadiz": "Plaza de Sevilla-Estación de Cádiz",
}
DAY_GROUPS = ("L-J", "V", "S", "D")


def reference_day(now, group):
    today = now.astimezone(MADRID).date()
    for offset in range(7):
        date = today + timedelta(days=offset)
        weekday = date.weekday()
        if (group == "L-J" and weekday <= 3 or
            group == "V" and weekday == 4 or
            group == "S" and weekday == 5 or
            group == "D" and weekday == 6):
            return date
    raise AssertionError("No reference date inside 7 days")


def build_train_rows(index, code, day, group):
    result = []
    by_id = {value: key for key, value in STATIONS.items()}
    for trip_id, static in index["trips"].items():
        if not service_active(index, trip_id, day):
            continue
        stops = sorted(
            [s for s in static["stops"] if s["stop_id"] in by_id],
            key=lambda s: s["seq"])
        for i, first in enumerate(stops):
            origin = by_id[first["stop_id"]]
            departure = _hhmm(first["departure"])
            for last in stops[i + 1:]:
                destination = by_id[last["stop_id"]]
                arrival = _hhmm(last["arrival"])
                if not departure or not arrival:
                    continue
                # A cross-midnight trip cannot be represented correctly by the
                # current non-dated departure/arrival display.
                if int(first["departure"].split(":")[0]) >= 24 or \
                   int(last["arrival"].split(":")[0]) >= 24:
                    continue
                result.append((origin + "-" + destination, {
                    "linea": code,
                    "tipo": "tren",
                    "salida": departure,
                    "llegada": arrival,
                    "parada_salida": STATION_LABELS[origin],
                    "parada_llegada": STATION_LABELS[destination],
                    "llegada_estimada": False,
                    "dias": group,
                    "aviso": "",
                    "fecha_servicio": day.isoformat(),
                    "trip_id": trip_id,
                    "fuente_horario": SOURCES[code],
                }))
    return result


def replace_ctan_trains(data, now, index_loader=None):
    """Use authoritative GTFS for trains; buses/boats remain untouched.

    If a GTFS source fails, its CMTBC trains stay visible in red as *unverified*,
    not as supposedly up-to-date official Renfe departures.
    Returns source diagnostics suitable for a Telegram report.
    """
    problems, stats = [], {}
    loader = index_loader or load_index
    for code in ("C-1", "MD"):
        try:
            index, warning = loader(code, now)
            groups = []
            for group in DAY_GROUPS:
                day = reference_day(now, group)
                groups.extend(build_train_rows(index, code, day, group))
            count = len(groups)
            if not count:
                raise RuntimeError("no active trips for any of the four day groups")
            for key, trips in data.items():
                trips[:] = [t for t in trips if t["linea"] != code]
            for route, train in groups:
                if route in data:
                    data[route].append(train)
            stats[code] = {"official_rows": count,
                           "dates": {g: reference_day(now, g).isoformat()
                                     for g in DAY_GROUPS}}
            if warning:
                problems.append(warning)
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            message = "No hay horarios Renfe verificados para {}: {}".format(code, exc)
            problems.append(message)
            for trips in data.values():
                for t in trips:
                    if t["linea"] == code:
                        t["aviso"] = message
    for trips in data.values():
        trips.sort(key=lambda t: (t["salida"], t["linea"]))
    return problems, stats
