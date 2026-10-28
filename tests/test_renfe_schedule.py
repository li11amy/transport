"""Official Renfe train schedules must replace only train rows, not CMTBC buses."""
import unittest
from datetime import datetime, date
from zoneinfo import ZoneInfo

from renfe_schedule import build_train_rows, reference_day, replace_ctan_trains

NOW = datetime(2026, 10, 28, 12, tzinfo=ZoneInfo("Europe/Madrid"))


def index():
    return {
        "trips": {"TRIP123": {
            "service": "WK", "route": "31C1", "stops": [
                {"stop_id": "51300", "seq": 1,
                 "arrival": "08:00:00", "departure": "08:00:00"},
                {"stop_id": "51400", "seq": 2,
                 "arrival": "08:09:00", "departure": "08:10:00"},
                {"stop_id": "51405", "seq": 3,
                 "arrival": "08:45:00", "departure": "08:45:00"},
            ]}},
        "calendars": {"WK": {
            "start_date": "20261001", "end_date": "20261231",
            "wednesday": "1", "friday": "1", "saturday": "1", "sunday": "1",
            "monday": "1", "tuesday": "1", "thursday": "1"}},
        "exceptions": {},
    }


class RenfeTrainScheduleTests(unittest.TestCase):
    def test_reference_days(self):
        self.assertEqual(reference_day(NOW, "L-J"), date(2026, 10, 28))
        self.assertEqual(reference_day(NOW, "V"), date(2026, 10, 30))
        self.assertEqual(reference_day(NOW, "S"), date(2026, 10, 31))
        self.assertEqual(reference_day(NOW, "D"), date(2026, 11, 1))

    def test_train_routes_and_exact_identity(self):
        rows = build_train_rows(index(), "C-1", NOW.date(), "L-J")
        routes = {route for route, _ in rows}
        self.assertEqual(routes, {
            "jerez-puerto", "jerez-cadiz", "puerto-cadiz"})
        by_route = dict(rows)
        self.assertEqual(by_route["puerto-cadiz"]["salida"], "08:10")
        self.assertEqual(by_route["puerto-cadiz"]["llegada"], "08:45")
        self.assertEqual(by_route["puerto-cadiz"]["trip_id"], "TRIP123")
        self.assertEqual(by_route["puerto-cadiz"]["fecha_servicio"], "2026-10-28")

    def test_keep_ctan_bus_but_replace_old_train(self):
        old_train = {"linea": "C-1", "tipo": "tren", "salida": "08:40",
                     "llegada": "09:15", "dias": "L-V", "aviso": ""}
        bus = {"linea": "M-051", "tipo": "bus", "salida": "07:00",
               "llegada": "08:00", "dias": "L-V", "aviso": ""}
        data = {"puerto-cadiz": [old_train, bus]}
        probs, stats = replace_ctan_trains(
            data, NOW, index_loader=lambda line, now: (index(), None))
        self.assertEqual(probs, [])
        self.assertIn("C-1", stats)
        self.assertEqual(sum(t["tipo"] == "bus" for t in data["puerto-cadiz"]), 1)
        self.assertNotIn(old_train, data["puerto-cadiz"])
        self.assertEqual([t["salida"] for t in data["puerto-cadiz"] if t["linea"]=="C-1"
                          and t["dias"]=="L-J"], ["08:10"])

    def test_failure_marks_old_trains_unverified(self):
        data = {"puerto-cadiz": [
            {"linea": "C-1", "tipo": "tren", "salida": "08:40",
             "llegada": "09:15", "dias": "L-V", "aviso": ""},
        ]}
        def fails(line, now):
            raise RuntimeError("offline")
        problems, stats = replace_ctan_trains(data, NOW, index_loader=fails)
        self.assertEqual(len(problems), 2)
        self.assertIn("No hay horarios Renfe verificados", data["puerto-cadiz"][0]["aviso"])
        self.assertEqual(stats, {})


if __name__ == "__main__":
    unittest.main()
