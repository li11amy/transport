"""Offline tests for split static shell + 15-minute live JSON refresh."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

import build_horarios as generator


SAMPLE = {
    "linea": "C-1",
    "tipo": "tren",
    "salida": "10:00",
    "llegada": "10:30",
    "parada_salida": "Estación FC",
    "parada_llegada": "Plaza de Sevilla-Estación de Cádiz",
    "llegada_estimada": False,
    "dias": "L-V",
    "aviso": "",
}


class DynamicJSONTests(unittest.TestCase):
    def test_data_only_preserves_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = Path(tmp) / "index.html"
            data_file = Path(tmp) / "transport_data.json"
            html.write_text("UNCHANGED SHELL", encoding="utf-8")
            with (
                patch.object(generator, "ROUTES", [("puerto", "cadiz")]),
                patch.object(generator, "source_url", return_value="https://example.invalid"),
                patch.object(generator, "fetch", return_value="unused"),
                patch.object(generator, "parse", return_value=([SAMPLE.copy()], [])),
                patch.object(generator, "report_issues"),
                patch.object(generator, "replace_ctan_trains", return_value=([], {})),
                patch.object(generator, "apply_changes", return_value={
                    "date": "2026-10-28",
                    "checked_at": "2026-10-28T20:00:00+01:00",
                    "issues": 0, "changes": 0,
                }),
                patch.object(generator, "OUTPUT", html),
                patch.object(generator, "DATA_OUTPUT", data_file),
            ):
                generator.build(data_only=True)
                self.assertEqual(html.read_text(encoding="utf-8"), "UNCHANGED SHELL")
                payload = json.loads(data_file.read_text(encoding="utf-8"))
                self.assertIn("puerto-cadiz", payload["data"])
                self.assertEqual(payload["data"]["puerto-cadiz"][0]["salida"], "10:00")
                self.assertEqual(payload["meta"]["changes"], 0)

    def test_consorcio_timeout_retries_once(self):
        class Response:
            text = "cached schedule replaced by network"
            def raise_for_status(self):
                return None
        with (
            patch.object(generator.requests, "get", side_effect=[
                requests.Timeout("slow"), Response()
            ]) as get,
            patch.object(generator.time, "sleep") as sleep,
        ):
            self.assertEqual(generator.fetch("https://example.invalid"), Response.text)
            self.assertEqual(get.call_count, 2)
            sleep.assert_called_once_with(2)

    def test_cached_bus_and_boat_marked_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "transport_data.json"
            cache.write_text(json.dumps({"data": {
                "puerto-cadiz": [
                    {"tipo": "bus", "linea": "M-051", "salida": "09:00",
                     "llegada": "10:00", "dias": "L-V", "aviso": ""},
                    {"tipo": "catamaran", "linea": "B-042", "salida": "09:00",
                     "llegada": "09:30", "dias": "L-V", "aviso": ""},
                    SAMPLE.copy(),
                ]
            }}), encoding="utf-8")
            with patch.object(generator, "DATA_OUTPUT", cache):
                rows = generator.cached_ctan_route("puerto-cadiz")
            self.assertEqual([row["tipo"] for row in rows], ["bus", "catamaran"])
            self.assertTrue(all("no verificado" in row["aviso"] for row in rows))

    def test_unavailable_consorcio_reuses_last_public_data_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            json_file = Path(tmp) / "transport_data.json"
            old = {"tipo": "bus", "linea": "M-051", "salida": "09:00",
                   "llegada": "10:00", "dias": "L-V", "aviso": ""}
            json_file.write_text(json.dumps({"data": {"puerto-cadiz": [old]}}),
                                 encoding="utf-8")
            with (
                patch.object(generator, "ROUTES", [("puerto", "cadiz")]),
                patch.object(generator, "fetch", side_effect=requests.Timeout("upstream")),
                patch.object(generator, "DATA_OUTPUT", json_file),
                patch.object(generator, "report_issues") as report,
                patch.object(generator, "replace_ctan_trains", return_value=([], {})),
                patch.object(generator, "apply_changes", return_value={
                    "date": "2026-10-28",
                    "checked_at": "2026-10-28T20:00:00+01:00",
                    "issues": 0, "changes": 0,
                }),
            ):
                generator.build(data_only=True)
            data = json.loads(json_file.read_text(encoding="utf-8"))["data"]
            self.assertEqual(data["puerto-cadiz"][0]["salida"], "09:00")
            self.assertIn("no verificado", data["puerto-cadiz"][0]["aviso"])
            self.assertTrue(report.called)

    def test_html_shell_fetches_dynamic_json(self):
        self.assertIn('fetch("./transport_data.json",{cache:"no-store"})', generator.HTML)
        self.assertIn("renderSourceStatus();", generator.HTML)
        self.assertIn("refreshData();", generator.HTML)
        self.assertIn("let DATA = __TRANSPORT_DATA__;", generator.HTML)


if __name__ == "__main__":
    unittest.main()
