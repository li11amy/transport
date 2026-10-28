"""Offline tests for Renfe GTFS static joins and service calendars."""
import io
import json
import tempfile
import unittest
import zipfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import patch

import renfe_static_gtfs as gtfs


def static_zip():
    tables = {
        "stop_times.txt": (
            "trip_id,stop_id,stop_sequence,arrival_time,departure_time\n"
            "C1A,51300,1,22:48:00,22:48:00\n"
            "C1A,51400,2,22:57:00,22:58:00\n"
            "C1A,51405,3,23:38:00,23:38:00\n"
            "UNRELATED,00000,1,12:00:00,12:00:00\n"
            "MDOLD,51300,1,21:45:00,21:45:00\n"
            "MDOLD,51400,2,22:03:00,22:04:00\n"
            "MDOLD,51405,3,22:30:00,22:30:00\n"),
        "trips.txt": (
            "route_id,service_id,trip_id\n"
            "31T0002C1,WK,C1A\n"
            "31T0002C1,WK,UNRELATED\n"
            "RMD,WK,MDOLD\n"),
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            "WK,1,1,1,1,1,0,0,20261001,20261231\n"),
        "calendar_dates.txt": (
            "service_id,date,exception_type\n"
            "WK,20261029,2\n"
            "WK,20261031,1\n"),
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for filename, text in tables.items():
            zf.writestr(filename, text)
    stream.seek(0)
    return stream


class StaticGTFS(unittest.TestCase):
    def test_local_stops_and_trip_id(self):
        with zipfile.ZipFile(static_zip()) as zf:
            index = gtfs.build_index_from_zip(zf)
        self.assertEqual(set(index["trips"]), {"C1A", "MDOLD"})
        self.assertEqual([x["stop_id"] for x in index["trips"]["C1A"]["stops"]],
                         ["51300", "51400", "51405"])
        self.assertEqual(index["trips"]["C1A"]["stops"][1]["departure"], "22:58:00")
        self.assertTrue(gtfs.service_active(index, "C1A", date(2026, 10, 28)))
        self.assertFalse(gtfs.service_active(index, "C1A", date(2026, 10, 29)))
        self.assertTrue(gtfs.service_active(index, "C1A", date(2026, 10, 31)))

    def test_date_embedded_in_md_trip_id(self):
        with zipfile.ZipFile(static_zip()) as zf:
            index = gtfs.build_index_from_zip(zf)
        index["trips"]["1303512026-10-27"] = index["trips"]["MDOLD"]
        self.assertFalse(gtfs.service_active(index, "1303512026-10-27", date(2026, 10, 28)))

    def test_index_is_cached_and_reused(self):
        with tempfile.TemporaryDirectory() as tempdir:
            now = datetime(2026, 10, 28, 12, tzinfo=ZoneInfo("Europe/Madrid"))
            with patch.object(gtfs, "_download_zip", return_value=zipfile.ZipFile(static_zip())) as fetch:
                first, warning = gtfs.load_index("C-1", now, cache_dir=tempdir)
                again, warning2 = gtfs.load_index("C-1", now, cache_dir=tempdir)
            self.assertIsNone(warning)
            self.assertIsNone(warning2)
            self.assertEqual(first, again)
            fetch.assert_called_once()
            self.assertTrue((Path(tempdir) / "cercanias.json").is_file())


if __name__ == "__main__":
    unittest.main()
