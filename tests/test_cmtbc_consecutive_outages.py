"""CMTBC: alert only on the second consecutive source failure.

The passenger-facing warning remains immediate; Telegram is delayed.
"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import build_horarios as h

T0 = datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc)
OUTAGE = {"route": "cadiz-puerto",
          "detail": "CMTBC sin respuesta; autobuses/barcos con datos anteriores (HTTPError)"}


class ConsecutiveCMTBCTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.sent = []
        self.mocks = [
            patch.object(h, "WARNINGS_FILE", root / "warnings.json"),
            patch.object(h, "ALERT_STATE_FILE", root / "alerts.sha256"),
            patch.object(h, "OUTAGE_STATE_FILE", root / "outages.json"),
            patch.object(h, "notify_telegram",
                         side_effect=lambda msg: self.sent.append(msg) or True),
        ]
        for mock in self.mocks:
            mock.start()
            self.addCleanup(mock.stop)
        self.root = root

    def report(self, issues, minutes=0):
        h.report_issues(issues, now=T0 + timedelta(minutes=minutes))
        return json.loads((self.root / "warnings.json").read_text())

    def test_first_failure_silent_second_alert_once_recovery_resets(self):
        first = self.report([OUTAGE], 0)
        self.assertEqual(self.sent, [])
        self.assertEqual(first["issues"], [OUTAGE])
        self.assertEqual(first["pending_outages"], [
            {"route": "cadiz-puerto", "count": 1}])
        self.assertFalse((self.root / "alerts.sha256").exists())

        second = self.report([OUTAGE], 15)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0].count("cadiz-puerto:"), 1)
        self.assertIn("dos comprobaciones consecutivas", self.sent[0])
        self.assertEqual(second["pending_outages"], [])

        # Status change from HTTP 500 to 503 is the same outage.
        different = dict(OUTAGE, detail=OUTAGE["detail"].replace(
            "HTTPError", "ConnectionError"))
        self.report([different], 30)
        self.assertEqual(len(self.sent), 1)

        recovered = self.report([], 45)
        self.assertEqual(recovered["recovered_routes"], ["cadiz-puerto"])
        self.assertEqual(self.sent.__len__(), 1)
        self.assertFalse((self.root / "alerts.sha256").exists())

        self.report([OUTAGE], 60)
        self.assertEqual(len(self.sent), 1)
        self.report([OUTAGE], 75)
        self.assertEqual(len(self.sent), 2)

    def test_gap_or_recovered_cycle_breaks_consecutive_streak(self):
        self.report([OUTAGE], 0)
        self.report([OUTAGE], 30)
        self.assertEqual(self.sent, [])  # 30 minutes != consecutive 15-min checks
        self.report([OUTAGE], 45)
        self.assertEqual(len(self.sent), 1)

    def test_other_source_errors_still_alert_immediately(self):
        other = {"route": "Renfe", "detail": "GTFS temporalmente no disponible"}
        self.report([OUTAGE, other], 0)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Renfe:", self.sent[0])
        self.assertNotIn("cadiz-puerto:", self.sent[0])
        self.report([OUTAGE, other], 15)
        self.assertEqual(len(self.sent), 2)
        self.assertIn("cadiz-puerto:", self.sent[-1])

    def test_different_routes_have_independent_counters(self):
        other = dict(OUTAGE, route="puerto-jerez")
        self.report([OUTAGE], 0)
        self.report([OUTAGE, other], 15)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("cadiz-puerto:", self.sent[0])
        self.assertNotIn("puerto-jerez:", self.sent[0])
        self.report([OUTAGE, other], 30)
        self.assertEqual(len(self.sent), 2)
        self.assertIn("puerto-jerez:", self.sent[-1])

    def test_fatal_incomplete_refresh_does_not_falsely_recover(self):
        self.report([OUTAGE], 0)
        error = {"route": "ERROR", "detail": "No safe cached timetable"}
        incomplete = self.report([error], 5)
        self.assertEqual(incomplete["recovered_routes"], [])
        self.assertIn("ERROR:", self.sent[0])
        self.report([OUTAGE], 15)
        self.assertEqual(len(self.sent), 2)
        self.assertIn("cadiz-puerto:", self.sent[-1])


if __name__ == "__main__":
    unittest.main()
