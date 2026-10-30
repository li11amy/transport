"""Offline regression tests: python3 -m unittest discover -s tests -v"""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import transport_updates as updates

TZ = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=TZ)


def epoch(hour, minute):
    return int(datetime(2026, 10, 28, hour, minute, tzinfo=TZ).timestamp())


def trip(line="C-1", kind="tren", departure="10:00", arrival="10:30", days="L-V"):
    return {
        "linea": line, "tipo": kind, "salida": departure, "llegada": arrival,
        "dias": days, "aviso": "", "parada_salida": "Estación FC",
        "parada_llegada": "Plaza de Sevilla-Estación de Cádiz",
        "llegada_estimada": False,
        **({"trip_id": "RENFE_TEST", "fecha_servicio": "2026-10-28"}
           if kind == "tren" else {}),
    }


def feed(stops, timestamp=None, relationship="SCHEDULED"):
    return {
        "header": {"timestamp": str(timestamp if timestamp is not None else int(NOW.timestamp()))},
        "entity": [{
            "id": "TU_TEST",
            "tripUpdate": {
                "trip": {"tripId": "RENFE_TEST", "scheduleRelationship": relationship},
                "stopTimeUpdate": stops,
            },
        }],
    }


def stop(station, scheduled, delay, kind="arrival"):
    return {
        "stopId": station,
        kind: {"time": str(scheduled + delay), "delay": delay},
    }


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass

    def json(self):
        return self.content

    @property
    def text(self):
        return self.content


class FakeHttp:
    def __init__(self, mapping):
        self.mapping = mapping

    def get(self, url, timeout):
        if url not in self.mapping:
            raise AssertionError("Unexpected GET " + url)
        return FakeResponse(self.mapping[url])


def static_index(trip_id="RENFE_TEST", first="51400", last="51405"):
    return {
        "trips": {
            trip_id: {"service": "WEEKDAYS", "route": "R1", "stops": [
                {"stop_id": first, "seq": 1, "arrival": "09:59:00",
                 "departure": "10:00:00"},
                {"stop_id": last, "seq": 2, "arrival": "10:30:00",
                 "departure": "10:31:00"},
            ]}
        },
        "calendars": {"WEEKDAYS": {
            "start_date": "20260101", "end_date": "20261231",
            "wednesday": "1", "tuesday": "1", "monday": "1",
            "thursday": "1", "friday": "1", "saturday": "0", "sunday": "0"}},
        "exceptions": {},
    }


def fake_index_loader(code, now):
    return static_index(), None


class ServiceUpdateTests(unittest.TestCase):
    def test_verified_rail_delay_preserves_planned_times(self):
        data = {"puerto-cadiz": [trip()]}
        live = feed([
            stop("51400", epoch(10, 0), 300, "departure"),
            stop("51405", epoch(10, 30), 300),
        ])
        http = FakeHttp({updates.RENFE["C-1"]: live,
                         updates.RENFE["MD"]: feed([])})
        events, problems = updates.rail_changes(data, NOW, http, index_loader=fake_index_loader)
        self.assertFalse(problems)
        # Exact +5 minutes remain visible on the website, not in Telegram.
        self.assertEqual(len(events), 0)
        self.assertEqual(data["puerto-cadiz"][0]["salida"], "10:00")
        self.assertEqual(data["puerto-cadiz"][0]["salida_actual"], "10:05")
        self.assertEqual(data["puerto-cadiz"][0]["llegada_actual"], "10:35")
        self.assertEqual(data["puerto-cadiz"][0]["estado"], "confirmed")

    def test_single_station_departure_is_confirmed(self):
        data = {"puerto-cadiz": [trip()]}
        http = FakeHttp({
            updates.RENFE["C-1"]: feed([stop("51400", epoch(10, 0), 300, "departure")]),
            updates.RENFE["MD"]: feed([])})
        events, problems = updates.rail_changes(
            data, NOW, http, index_loader=fake_index_loader)
        self.assertFalse(problems)
        self.assertEqual(len(events), 0)
        self.assertEqual(data["puerto-cadiz"][0]["salida_actual"], "10:05")
        self.assertNotIn("llegada_actual", data["puerto-cadiz"][0])

    def test_origin_arrival_does_not_change_departure(self):
        data = {"puerto-cadiz": [trip()]}
        http = FakeHttp({
            updates.RENFE["C-1"]: feed([stop("51400", epoch(9, 59), 180, "arrival")]),
            updates.RENFE["MD"]: feed([])})
        events, problems = updates.rail_changes(
            data, NOW, http, index_loader=fake_index_loader)
        self.assertFalse(problems)
        self.assertEqual(len(events), 0)
        self.assertEqual(data["puerto-cadiz"][0]["estado"], "warning")
        self.assertNotIn("salida_actual", data["puerto-cadiz"][0])

    def test_six_minute_arrival_notifies_but_five_minute_does_not(self):
        for minutes in (5, 6):
            with self.subTest(minutes=minutes):
                data = {"puerto-cadiz": [trip()]}
                delayed = feed([stop("51405", epoch(10, 30), minutes * 60)])
                http = FakeHttp({
                    updates.RENFE["C-1"]: delayed,
                    updates.RENFE["MD"]: feed([]),
                })
                events, problems = updates.rail_changes(
                    data, NOW, http, index_loader=fake_index_loader)
                self.assertFalse(problems)
                self.assertEqual(len(events), 1 if minutes == 6 else 0)
                self.assertEqual(
                    data["puerto-cadiz"][0]["llegada_actual"],
                    "10:{:02d}".format(30 + minutes))

    def test_earlier_departure_one_minute_always_notifies(self):
        data = {"puerto-cadiz": [trip()]}
        earlier = feed([stop("51400", epoch(10, 0), -60, "departure")])
        http = FakeHttp({
            updates.RENFE["C-1"]: earlier,
            updates.RENFE["MD"]: feed([]),
        })
        events, problems = updates.rail_changes(
            data, NOW, http, index_loader=fake_index_loader)
        self.assertFalse(problems)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["metrics"]["dep_early"], 1)
        self.assertEqual(data["puerto-cadiz"][0]["salida_actual"], "09:59")

    def test_full_train_cancellation_always_notifies(self):
        data = {"puerto-cadiz": [trip()]}
        cancelled = feed([], relationship="CANCELED")
        http = FakeHttp({
            updates.RENFE["C-1"]: cancelled,
            updates.RENFE["MD"]: feed([]),
        })
        events, problems = updates.rail_changes(
            data, NOW, http, index_loader=fake_index_loader)
        self.assertFalse(problems)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "cancelled")
        self.assertEqual(data["puerto-cadiz"][0]["estado"], "cancelled")

    def test_md_impossible_70_min_early_arrival_is_not_a_fact_or_telegram_alert(self):
        # Live incident 30 Oct: MD Cádiz 17:24 -> El Puerto 17:48, but
        # GTFS-RT reported 16:38 at destination (-70 min).
        # A train cannot arrive before its unmodified 17:24 departure.
        from datetime import datetime
        now = datetime(2026, 10, 28, 17, 45, tzinfo=TZ)
        def md_index(code, when):
            index = static_index(first="51405", last="51400")
            stops = index["trips"]["RENFE_TEST"]["stops"]
            stops[0]["departure"] = "17:24:00"
            stops[1]["arrival"] = "17:48:00"
            return index, None

        trip_row = trip(line="MD", departure="17:24", arrival="17:48")
        trip_row["parada_salida"] = "Estación de Cádiz"
        trip_row["parada_llegada"] = "Estación FC"
        data = {"cadiz-puerto": [trip_row]}
        early_at_destination = feed([
            stop("51400", epoch(17, 48), -70 * 60)
        ], timestamp=int(now.timestamp()))
        http = FakeHttp({updates.RENFE["C-1"]: feed([], timestamp=int(now.timestamp())),
                         updates.RENFE["MD"]: early_at_destination})
        events, problems = updates.rail_changes(
            data, now, http, index_loader=md_index)
        self.assertFalse(problems)
        self.assertEqual(events, [])
        self.assertEqual(trip_row["estado"], "warning")
        self.assertNotIn("llegada_actual", trip_row)
        self.assertIn("incoherente", trip_row["detalle"])
        self.assertEqual(trip_row["llegada"], "17:48")

    def test_md_valid_delayed_arrival_still_notifies(self):
        from datetime import datetime
        now = datetime(2026, 10, 28, 17, 45, tzinfo=TZ)
        index = static_index(first="51405",last="51400")
        index["trips"]["RENFE_TEST"]["stops"][0]["departure"] = "17:24:00"
        index["trips"]["RENFE_TEST"]["stops"][1]["arrival"] = "17:48:00"
        row = trip(line="MD", departure="17:24", arrival="17:48")
        data = {"cadiz-puerto": [row]}
        forecast = feed([stop("51400", epoch(17, 48), 6 * 60)],
                        timestamp=int(now.timestamp()))
        http = FakeHttp({updates.RENFE["C-1"]: feed([], timestamp=int(now.timestamp())),
                         updates.RENFE["MD"]: forecast})
        events, problems = updates.rail_changes(
            data, now, http, index_loader=lambda code, time: (index,None))
        self.assertFalse(problems)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["metrics"]["arr_late"], 6)
        self.assertEqual(row["llegada_actual"], "17:54")
        self.assertEqual(row["estado"], "confirmed")

    def test_segment_validation_overnight_and_legitimate_early_departure(self):
        self.assertFalse(updates.plausible_segment_arrival(
            "17:24", "17:48", None, "16:38"))
        self.assertTrue(updates.plausible_segment_arrival(
            "17:24", "17:48", "16:20", "16:38"))
        self.assertTrue(updates.plausible_segment_arrival(
            "23:50", "00:15", None, "00:20"))
        self.assertFalse(updates.plausible_segment_arrival(
            "23:50", "00:15", None, "23:10"))
        self.assertFalse(updates.plausible_segment_arrival(
            "17:24", "17:48", None, "17:25"))

    def test_yesterdays_md_train_is_ignored(self):
        data = {"puerto-cadiz": [trip("MD")]}
        delayed = feed([stop("51400", epoch(10, 0), 180, "departure")])
        delayed["entity"][0]["tripUpdate"]["trip"]["tripId"] = "1303512026-10-27"
        index = static_index("1303512026-10-27")
        http = FakeHttp({updates.RENFE["C-1"]: feed([]),
                         updates.RENFE["MD"]: delayed})
        events, problems = updates.rail_changes(
            data, NOW, http, index_loader=lambda code, now: (index, None))
        self.assertFalse(problems)
        self.assertEqual(events, [])
        self.assertNotIn("estado", data["puerto-cadiz"][0])

    def test_stale_feed_ignored(self):
        data = {"puerto-cadiz": [trip()]}
        delayed = feed([
            stop("51400", epoch(10, 0), 300, "departure"),
            stop("51405", epoch(10, 30), 300)], epoch(8, 0))
        http = FakeHttp({updates.RENFE["C-1"]: delayed, updates.RENFE["MD"]: feed([])})
        events, problems = updates.rail_changes(data, NOW, http, index_loader=fake_index_loader)
        self.assertFalse(events)
        self.assertTrue(any("stale" in issue for issue in problems))
        self.assertNotIn("salida_actual", data["puerto-cadiz"][0])

    def test_old_bus_notice_not_flagged(self):
        data = {"jerez-puerto": [trip("M-051", "bus")]}
        html = '<a href="horarios_lineas_tabla.php?linea=17">M-051/Cádiz-Jerez</a>'
        old = '<a href="/es/noticia.php?id=4">02/07/2025 Nuevas tarifas</a>'
        http = FakeHttp({
            updates.BUS_LINES_URL: html,
            updates.BUS_NOTICE_URL.format("17"): old,
        })
        events, problems = updates.bus_notices(data, NOW, http)
        self.assertEqual(events, [])
        self.assertEqual(problems, [])
        self.assertNotIn("estado", data["jerez-puerto"][0])

    def test_bus_notice_is_advisory_and_one_event(self):
        data = {"jerez-puerto": [trip("M-051", "bus"), trip("M-051", "bus", "11:00", "11:30")]}
        html = '<a href="horarios_lineas_tabla.php?linea=17">M-051/Cádiz-Jerez</a>'
        news = '<a href="/es/noticia.php?id=4">27/10/2026 Modificación del servicio M-051</a>'
        http = FakeHttp({
            updates.BUS_LINES_URL: html,
            updates.BUS_NOTICE_URL.format("17"): news,
        })
        events, problems = updates.bus_notices(data, NOW, http)
        self.assertFalse(problems)
        self.assertEqual(len(events), 1)
        self.assertEqual([x["estado"] for x in data["jerez-puerto"]], ["warning", "warning"])
        self.assertEqual(data["jerez-puerto"][0]["salida"], "10:00")

    def test_notification_dedup(self):
        event = {"id": "bus:M-051", "route": "puerto-cadiz", "line": "M-051",
                 "detail": "Cambio", "source": "https://example.org", "date": "2026-10-28"}
        messages = []
        with tempfile.TemporaryDirectory() as td:
            with patch.object(updates, "STATE_FILE", Path(td) / "sent.json"):
                updates.notify_events([event], lambda x: messages.append(x) or True, NOW)
                updates.notify_events([event], lambda x: messages.append(x) or True, NOW)
        self.assertEqual(len(messages), 1)


if __name__ == "__main__":
    unittest.main()
