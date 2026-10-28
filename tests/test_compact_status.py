"""Regression checks for the compact, accessible timetable alert UI."""
import unittest
from bs4 import BeautifulSoup
from build_horarios import HTML


class CompactStatusTests(unittest.TestCase):
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
        self.assertIn("tr.service-warning,tr.service-confirmed{", HTML) if False else None
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
