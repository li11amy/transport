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


class ServiceUpdateTests(unittest.TestCase):
    def test_verified_rail_delay_preserves_planned_times(self):
        data = {"puerto-cadiz": [trip()]}
        live = feed([
            stop("51400", epoch(10, 0), 300, "departure"),
            stop("51405", epoch(10, 30), 300),
        ])
        http = FakeHttp({updates.RENFE["C-1"]: live,
                         updates.RENFE["MD"]: feed([])})
        events, problems = updates.rail_changes(data, NOW, http)
        self.assertFalse(problems)
        self.assertEqual(len(events), 1)
        self.assertEqual(data["puerto-cadiz"][0]["salida"], "10:00")
        self.assertEqual(data["puerto-cadiz"][0]["salida_actual"], "10:05")
        self.assertEqual(data["puerto-cadiz"][0]["llegada_actual"], "10:35")
        self.assertEqual(data["puerto-cadiz"][0]["estado"], "confirmed")

    def test_single_station_does_not_rewrite_train(self):
        data = {"puerto-cadiz": [trip()]}
        http = FakeHttp({
            updates.RENFE["C-1"]: feed([stop("51400", epoch(10, 0), 300, "departure")]),
            updates.RENFE["MD"]: feed([])})
        events, problems = updates.rail_changes(data, NOW, http)
        self.assertFalse(problems)
        self.assertFalse(events)
        self.assertNotIn("estado", data["puerto-cadiz"][0])

    def test_stale_feed_ignored(self):
        data = {"puerto-cadiz": [trip()]}
        delayed = feed([
            stop("51400", epoch(10, 0), 300, "departure"),
            stop("51405", epoch(10, 30), 300)], epoch(8, 0))
        http = FakeHttp({updates.RENFE["C-1"]: delayed, updates.RENFE["MD"]: feed([])})
        events, problems = updates.rail_changes(data, NOW, http)
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
