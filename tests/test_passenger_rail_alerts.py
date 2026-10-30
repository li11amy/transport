"""Passenger-facing service changes must be useful and never preview raw GTFS files."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import transport_updates as updates
from build_horarios import HTML, notify_telegram


class PassengerRailAlertTests(unittest.TestCase):
    def test_one_minute_arrival_only(self):
        text = updates._passenger_rail_times("11:20", "11:29", None, "11:30")
        self.assertEqual(text, "Renfe · Salida 11:20 · Llegada 11:30 (+1 min)")
        self.assertNotIn("previsto 11:20 →", text)

    def test_departure_only_and_both_endpoints(self):
        self.assertEqual(
            updates._passenger_rail_times("11:20", "11:29", "11:25", None),
            "Renfe · Salida 11:25 (+5 min) · Llegada 11:29")
        self.assertEqual(
            updates._passenger_rail_times("11:20", "11:29", "11:17", "11:31"),
            "Renfe · Salida 11:17 (-3 min) · Llegada 11:31 (+2 min)")
        self.assertEqual(
            updates._passenger_rail_times("23:58", "00:30", "00:02", "00:33"),
            "Renfe · Salida 00:02 (+4 min) · Llegada 00:33 (+3 min)")

    def test_no_machine_json_urls_for_rail_alerts(self):
        for code, link in updates.RENFE.items():
            event = {
                "date": "2026-10-29", "route": "jerez-cadiz",
                "line": code, "detail": "Renfe · Salida 11:20 · Llegada 11:30 (+1 min)",
                "source": link,
            }
            message = updates.format_notification(event)
            self.assertNotIn(".json", message)
            self.assertNotIn("gtfsrt.renfe.com", message)
            self.assertIn("Jerez → Cádiz", message)
            self.assertIn("(+1 min)", message)
            if code == "C-1":
                self.assertIn("https://tiempo-real.renfe.com/?lang=es", message)
            else:
                self.assertNotIn("Fuente:", message)
                self.assertNotIn("MD: datos oficiales", message)
                self.assertNotIn("http", message)

    def test_web_panel_never_offers_raw_gtfs_json_to_passengers(self):
        self.assertIn("technicalRenfe", HTML)
        self.assertIn("Consultar Cercanías en Renfe", HTML)
        self.assertNotIn('source.textContent="Fuente: Renfe (datos oficiales en tiempo real)"', HTML)
        self.assertIn("https://tiempo-real.renfe.com/?lang=es", HTML)

    def test_other_source_urls_are_preserved(self):
        e = {"date": "2026-10-29", "route": "cadiz-puerto",
             "line": "B-042", "detail": "Aviso",
             "source": "https://cmtbc.es/?op=maritimo"}
        self.assertIn(e["source"], updates.format_notification(e))

    def test_sendmessage_disables_any_telegram_link_preview(self):
        with patch.dict("os.environ", {
            "TELEGRAM_BOT_TOKEN": "test",
            "TELEGRAM_CHAT_ID": "123",
        }, clear=True):
            with patch("build_horarios.requests.post") as send:
                send.return_value.json.return_value = {"ok": True}
                send.return_value.raise_for_status.return_value = None
                self.assertTrue(notify_telegram("Enlace: https://example.org"))
                payload = send.call_args.kwargs["data"]
                self.assertTrue(json.loads(payload["link_preview_options"])["is_disabled"])


if __name__ == "__main__":
    unittest.main()
