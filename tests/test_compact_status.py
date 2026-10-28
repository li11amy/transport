"""Regression checks for the compact, accessible timetable alert UI."""
import unittest
from bs4 import BeautifulSoup
from build_horarios import HTML


class CompactStatusTests(unittest.TestCase):
    def test_centered_header_and_install_prompt(self):
        dom = BeautifulSoup(HTML, "html.parser")
        self.assertIsNotNone(dom.select_one(".page-heading h1"))
        self.assertEqual(dom.select_one(".area-label").get_text(strip=True),
                         "El Puerto · Cádiz · Jerez")
        self.assertIsNotNone(dom.select_one("#installButton"))
        self.assertIsNotNone(dom.select_one("#installHelp[hidden]"))
        self.assertIn('window.addEventListener("beforeinstallprompt"', HTML)
        self.assertIn('window.addEventListener("appinstalled"', HTML)
        self.assertIn('const choice=await prompt.prompt()', HTML)
        self.assertIn('window.matchMedia("(display-mode: standalone)")', HTML)
        self.assertIn("Añadir a pantalla de inicio", HTML)
        self.assertIn("h1{font-size:clamp(23px,5vw,26px);margin:4px 0 5px;text-align:center", HTML)

    def test_boat_status_and_native_install_only(self):
        dom = BeautifulSoup(HTML, "html.parser")
        self.assertIsNotNone(dom.select_one("#boatReference[hidden]"))
        self.assertIsNotNone(dom.select_one("#installButton[hidden]"))
        self.assertIn('installButton.hidden=installedMode()||!deferredInstallPrompt', HTML)
        self.assertIn('marine.textContent="⛴ B-042 · Operativo"', HTML)
        self.assertIn('marine.textContent="⛴ B-042 · Incidencias"', HTML)
        self.assertIn('marine.textContent="⛴ B-042 · Sin verificar"', HTML)

    def test_one_legend_and_one_global_train_date(self):
        dom = BeautifulSoup(HTML, "html.parser")
        self.assertEqual(len(dom.select("#warningSummary")), 1)
        self.assertEqual(len(dom.select("#trainReference")), 1)
        self.assertEqual(len(dom.select(".status-dot.cancelled")), 1)
        self.assertEqual(len(dom.select(".status-dot.changed")), 1)
        self.assertNotIn("Atención: ", HTML)
        self.assertNotIn("dateLabel.textContent", HTML)

    def test_status_colors_and_disclosure_are_consistent(self):
        self.assertIn('if(cancelled) tr.classList.add("service-cancelled")', HTML)
        self.assertIn('else if(marked) tr.classList.add("service-warning")', HTML)
        self.assertIn("tr.uncertain,tr.service-warning,tr.service-confirmed{background:#fff3d1}", HTML)
        self.assertIn('extra.hidden=true;', HTML)
        self.assertIn('tr.addEventListener("keydown"', HTML)
        self.assertIn('tr.setAttribute("aria-expanded",String(!extra.hidden))', HTML)
        self.assertIn('source.rel="noopener noreferrer"', HTML)
        self.assertNotIn('line.appendChild(detail)', HTML)

    def test_destination_stop_name_is_used_not_city_key(self):
        self.assertIn("t.parada_llegada,toCity,t.tipo", HTML)
        self.assertNotIn("t.llegada,toCity,t.tipo", HTML)

    def test_confirmed_time_is_displayed_without_duplicate_old_time(self):
        self.assertIn('const actual=status==="confirmed"', HTML)
        self.assertIn('actual&&t.salida_actual?t.salida_actual:t.salida', HTML)
        self.assertIn('actual&&t.llegada_actual?t.llegada_actual:t.llegada', HTML)
        self.assertNotIn("service-planned", HTML)


if __name__ == "__main__":
    unittest.main()
