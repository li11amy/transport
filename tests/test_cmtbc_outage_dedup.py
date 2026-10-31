"""Regression: CMTBC outages are one warning per route, not per cached service."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
import build_horarios as h


def cached_bus(n):
    return {
        "tipo": "bus" if n % 3 else "catamaran",
        "linea": "M-040" if n % 3 else "B-042",
        "salida": "10:00", "llegada": "10:30",
        "dias": "L-D", "aviso": h.CMTBC_STALE_NOTICE,
        "parada_salida": "Cádiz", "parada_llegada": "El Puerto",
    }


class CMTBCAlertTests(unittest.TestCase):
    def test_sixty_cached_rows_produce_one_route_warning(self):
        sent = []
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def sender(message):
                sent.append(message)
                return True

            with patch.object(h, "ROUTES", [("cadiz", "puerto")]), \
                 patch.object(h, "DATA_OUTPUT", root / "transport_data.json"), \
                 patch.object(h, "WARNINGS_FILE", root / "warnings.json"), \
                 patch.object(h, "ALERT_STATE_FILE", root / "alert.sha256"), \
                 patch.object(h, "fetch", side_effect=requests.HTTPError("CMTBC 503")), \
                 patch.object(h, "cached_ctan_route", return_value=[
                     cached_bus(i) for i in range(60)]), \
                 patch.object(h, "replace_ctan_trains", return_value=([], {})), \
                 patch.object(h, "apply_changes", return_value={
                     "date": "2026-10-31", "checked_at": "2026-10-31T05:30:00+01:00",
                     "issues": 0, "changes": 0,
                 }), \
                 patch.object(h, "notify_telegram", side_effect=sender):
                h.build(data_only=True)
                h.build(data_only=True)

            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0].count("cadiz-puerto:"), 1)
            self.assertNotIn("… и ещё", sent[0])
            self.assertIn("CMTBC sin respuesta", sent[0])
            self.assertNotIn("Consorcio sin respuesta", sent[0])
            diagnostics = json.loads((root / "warnings.json").read_text())
            self.assertEqual(len(diagnostics["issues"]), 1)
            self.assertEqual(diagnostics["duplicates_suppressed"], 0)
            public = json.loads((root / "transport_data.json").read_text())
            entries = public["data"]["cadiz-puerto"]
            self.assertEqual(len(entries), 60)
            self.assertTrue(all(x["aviso"] == h.CMTBC_STALE_NOTICE for x in entries))
            self.assertEqual(entries[0]["salida"], "10:00")

    def test_duplicate_details_dedup_and_order_stability(self):
        messages = []
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            one = {"route": "cadiz-puerto", "detail": "CMTBC sin respuesta"}
            two = {"route": "jerez-puerto", "detail": "CMTBC sin respuesta"}
            distinct = {"route": "cadiz-puerto", "detail": "Código de días desconocido"}
            with patch.object(h, "WARNINGS_FILE", root / "warnings.json"), \
                 patch.object(h, "ALERT_STATE_FILE", root / "alert.sha256"), \
                 patch.object(h, "notify_telegram",
                              side_effect=lambda message: messages.append(message) or True):
                h.report_issues([one] * 50 + [two] * 9 + [distinct])
                h.report_issues([distinct, two, one])
                self.assertEqual(len(messages), 1)
                self.assertEqual(messages[0].count("CMTBC sin respuesta"), 2)
                self.assertEqual(messages[0].count("Código de días desconocido"), 1)
                self.assertNotIn("… и ещё", messages[0])
                self.assertEqual(
                    len(json.loads((root / "warnings.json").read_text())["issues"]), 3)
                # Once recovered, the same outage is genuinely new.
                h.report_issues([])
                self.assertFalse((root / "alert.sha256").exists())
                h.report_issues([one])
                self.assertEqual(len(messages), 2)

    def test_retry_http_503_once_but_never_403(self):
        class Response:
            def __init__(self, code):
                self.status_code = code
                self.text = "<html>OK</html>"
            def raise_for_status(self):
                if self.status_code >= 400:
                    raise requests.HTTPError("HTTP {}".format(self.status_code),
                                             response=self)

        with patch.object(h.requests, "get",
                          side_effect=[Response(503), Response(200)]) as get, \
             patch.object(h.time, "sleep") as sleep:
            self.assertEqual(h.fetch("https://example.invalid"), "<html>OK</html>")
            self.assertEqual(get.call_count, 2)
            sleep.assert_called_once_with(2)
        with patch.object(h.requests, "get", return_value=Response(403)) as get, \
             patch.object(h.time, "sleep") as sleep:
            with self.assertRaises(requests.HTTPError):
                h.fetch("https://example.invalid")
            self.assertEqual(get.call_count, 1)
            sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
