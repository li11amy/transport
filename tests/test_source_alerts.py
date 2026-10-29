"""Verified-source train disruption notices: strike != cancellation."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from source_alerts import apply_source_alerts, load_alerts
from build_horarios import HTML

NOW=datetime(2026,10,29,10,20,tzinfo=ZoneInfo("Europe/Madrid"))

def rows():
    return {
        "puerto-cadiz": [
            {"tipo":"tren","linea":"C-1","salida":"08:00",
             "fecha_servicio":"2026-10-29","aviso":""},
            {"tipo":"tren","linea":"MD","salida":"10:00",
             "fecha_servicio":"2026-10-29","aviso":"",
             "estado":"cancelled","detalle":"Renfe: servicio cancelado"},
            {"tipo":"bus","linea":"M-060","salida":"08:00","aviso":""},
        ],
        "jerez-cadiz": [
            {"tipo":"tren","linea":"C-1","salida":"09:00",
             "fecha_servicio":"2026-10-30","aviso":""},
            {"tipo":"tren","linea":"MD","salida":"12:00",
             "fecha_servicio":"2026-10-29","aviso":"",
             "estado":"confirmed","salida_actual":"12:03",
             "detalle":"Renfe confirma retraso"},
        ],
    }

class StrikeTests(unittest.TestCase):
    def test_today_verified_source_marks_unknown_trains_yellow_only(self):
        data=rows()
        events, meta=apply_source_alerts(data,NOW)
        self.assertEqual(len(events),1)
        self.assertEqual(meta[0]["affected_rows"],2)
        self.assertEqual(data["puerto-cadiz"][0]["estado"],"warning")
        self.assertTrue(data["puerto-cadiz"][0]["aviso"])
        self.assertEqual(data["puerto-cadiz"][1]["estado"],"cancelled")
        self.assertEqual(data["puerto-cadiz"][1]["detalle"],"Renfe: servicio cancelado")
        self.assertNotIn("estado",data["puerto-cadiz"][2])
        self.assertNotIn("estado",data["jerez-cadiz"][0])
        self.assertEqual(data["jerez-cadiz"][1]["estado"],"confirmed")
        self.assertIn("Renfe confirma retraso",data["jerez-cadiz"][1]["detalle"])

    def test_advisory_expires_without_impacting_next_day(self):
        data=rows()
        events, meta=apply_source_alerts(
            data,datetime(2026,10,30,12,tzinfo=ZoneInfo("Europe/Madrid")))
        self.assertEqual((events,meta),([],[]))
        self.assertNotIn("estado",data["puerto-cadiz"][0])

    def test_only_source_verified_alerts(self):
        alert=dict(load_alerts()[0])
        alert["verified"]=False
        events, meta=apply_source_alerts(rows(),NOW,[alert])
        self.assertEqual((events,meta),([],[]))

    def test_metadata_display(self):
        self.assertIn('id="officialAlerts"',HTML)
        self.assertIn("SERVICE_META.official_alerts||[]",HTML)
        self.assertIn('alertBox.hidden=activeAlerts.length===0',HTML)

if __name__=="__main__":
    unittest.main()
