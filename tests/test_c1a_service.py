"""C-1a university rail service must never appear under Bus."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_horarios import HTML, build, parse


EXAMPLE = """<table>
<tr><th>Línea</th><th colspan="1">El Puerto</th><th colspan="1">Jerez</th><th>Días</th><th>Notas</th></tr>
<tr><th>Estación FC</th><th>Estación de Jerez</th></tr>
<tr><td>C-1 a</td><td>08:11</td><td>08:20</td><td>L-V</td><td>Servicio universitario</td></tr>
<tr><td>M-580</td><td>08:25</td><td>08:45</td><td>L-V</td><td></td></tr>
</table>"""


def load_patcher():
    path = Path(__file__).resolve().parents[1] / "deploy" / "patch-c1a-filter.py"
    spec = importlib.util.spec_from_file_location("c1a_patch", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class C1aTests(unittest.TestCase):
    def test_c1a_is_rail_and_unverified_university_service(self):
        rows, dropped = parse(EXAMPLE, "puerto", "jerez")
        self.assertEqual(dropped, [])
        self.assertEqual(rows[0]["linea"], "C-1 a")
        self.assertEqual(rows[0]["tipo"], "tren")
        self.assertEqual((rows[0]["salida"], rows[0]["llegada"]), ("08:11", "08:20"))
        self.assertIn("días lectivos universitarios", rows[0]["aviso"])
        self.assertIn("sin confirmar en GTFS", rows[0]["aviso"])
        self.assertEqual(rows[1]["tipo"], "bus")

    def test_unverified_c1a_is_not_reported_as_new_incident(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "data.json"
            with (
                patch("build_horarios.ROUTES", [("puerto", "jerez")]),
                patch("build_horarios.fetch", return_value=EXAMPLE),
                patch("build_horarios.report_issues") as report,
                patch("build_horarios.replace_ctan_trains", return_value=([], {})),
                patch("build_horarios.apply_changes", return_value={
                    "date": "2026-11-11",
                    "checked_at": "2026-11-11T13:00:00+01:00",
                    "issues": 0, "changes": 0,
                }),
                patch("build_horarios.DATA_OUTPUT", output),
            ):
                build(data_only=True)
            report.assert_called_once_with([])
            self.assertEqual(
                next(x for x in __import__("json").loads(output.read_text())
                     ["data"]["puerto-jerez"] if x["linea"] == "C-1 a")["tipo"],
                "tren",
            )

    def test_day_specific_renfe_duplicate_filter_and_bus_only_alert(self):
        self.assertIn('const officialC1=selected.filter(t=>t.tipo==="tren"', HTML)
        self.assertIn('closeClock(o.salida,t.salida)&&closeClock(o.llegada,t.llegada)', HTML)
        self.assertIn('const activeAlerts=types.has("tren")&&day===todayGroup()', HTML)

    def test_safe_public_shell_patch(self):
        m = load_patcher()
        old = HTML.replace(m.filter_block(HTML), m.OLD_FILTER)
        old = old.replace(m.NEW_ALERT, m.OLD_ALERT)
        self.assertNotEqual(old, HTML)
        self.assertEqual(m.patch_html(old, HTML), HTML)
        self.assertEqual(m.patch_html(HTML, HTML), HTML)
        self.assertRaises(ValueError, m.patch_html,
                          old.replace(m.OLD_FILTER, "unknown source changes"), HTML)


if __name__ == "__main__":
    unittest.main()
