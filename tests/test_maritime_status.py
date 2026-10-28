"""Offline regressions for official CMTBC B-042 live maritime status."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from maritime_status import cancelled_departures, evaluate_status, live_maritime_changes

NOW=datetime(2026,10,28,12,0,tzinfo=ZoneInfo("Europe/Madrid"))

def ferry(route,hour):
    return {"linea":"B-042","tipo":"catamaran","salida":hour,"llegada":"13:00",
            "dias":"L-V","aviso":""}

def data():
    return {
        "cadiz-puerto":[ferry("cadiz-puerto","11:20"),ferry("cadiz-puerto","14:35")],
        "puerto-cadiz":[ferry("puerto-cadiz","12:25"),ferry("puerto-cadiz","15:15")],
    }

def status(suspended=False, window=None, upcoming=None, checked="2026-10-28 12:00:00"):
    return {"fecha_consulta":checked,"lineas":{
        "B-042":{"codigo":"B-042","suspendida":suspended,
                 "suspension":window,"proxima":upcoming}}}

def window(text):
    return {"fecha_inicio":"2026-10-28 10:30:00",
            "fecha_fin":"2026-10-28 16:00:00",
            "causa":"Motivos operacionales","texto":text}

class FakeResponse:
    def __init__(self, body):
        self.body=body
    def raise_for_status(self):
        return None
    def json(self):
        return self.body
class FakeHttp:
    def __init__(self,body):
        self.body=body
    def get(self,url,timeout):
        return FakeResponse(self.body)

class MarineTests(unittest.TestCase):
    def test_live_operational_is_white(self):
        rows=data()
        changes,meta=evaluate_status(rows,NOW,status())
        self.assertFalse(changes)
        self.assertTrue(meta["operational"])
        self.assertNotIn("estado",rows["cadiz-puerto"][0])

    def test_partial_suspension_exact_departures_red_only(self):
        rows=data()
        content=("""
        Debido a motivos operacionales queda suspendida la navegación:
        Salidas desde Cádiz destino El Puerto: 11:20
        Salidas desde El Puerto destino Cádiz: 15:15
        Servicios alternativos por carretera:
        Salidas desde Cádiz destino El Puerto: 14:35
        """)
        changes,meta=evaluate_status(rows,NOW,status(True,window(content)))
        self.assertEqual(meta["red"],2)
        self.assertEqual({(a,b) for a,b,state in changes if state=="cancelled"},
                         {("cadiz-puerto","11:20"),("puerto-cadiz","15:15")})
        self.assertNotIn("estado",rows["cadiz-puerto"][1])
        self.assertNotIn("estado",rows["puerto-cadiz"][0])

    def test_full_suspension_red_within_window(self):
        rows=data()
        _,meta=evaluate_status(rows,NOW,status(True,window("Suspensión total: todos los servicios.")))
        self.assertEqual(meta["red"],4)

    def test_ambiguous_suspension_warns_not_cancelled(self):
        rows=data()
        _,meta=evaluate_status(rows,NOW,status(True,window("Posibles interrupciones del servicio.")))
        self.assertEqual(meta["red"],0)
        self.assertEqual(meta["yellow"],4)

    def test_future_suspension_other_day_does_not_affect_today(self):
        rows=data()
        future={"fecha_inicio":"2026-10-29 10:30:00",
                "fecha_fin":"2026-10-29 16:00:00","texto":"todos los servicios"}
        changes,_=evaluate_status(rows,NOW,status(False,upcoming=future))
        self.assertEqual(changes,[])
        self.assertNotIn("estado",rows["cadiz-puerto"][0])

    def test_unavailable_status_warns_and_notifies_once(self):
        rows=data()
        events,errors=live_maritime_changes(
            rows,NOW,session=FakeHttp(status(checked="2026-10-21 12:00:00")))
        self.assertEqual(len(errors),1)
        self.assertEqual(len(events),1)
        self.assertEqual(rows["puerto-cadiz"][0]["estado"],"warning")

    def test_existing_unverified_announcement_cleared_on_normal(self):
        rows=data()
        rows["cadiz-puerto"][0].update(
            {"estado":"warning","detalle":"old","fecha_cambio":"2026-10-28"})
        evaluate_status(rows,NOW,status())
        self.assertNotIn("estado",rows["cadiz-puerto"][0])

    def test_parsed_times_exclude_alternative_buses(self):
        found=cancelled_departures(
            "Salidas desde Cádiz destino El Puerto: 11:20 14:35<br>"
            "Salidas desde El Puerto destino Cádiz: 12:25<br>"
            "Servicios alternativos por carretera:"
            " Salidas desde Cádiz destino El Puerto: 10:00")
        self.assertEqual(found,{"cadiz-puerto":{"11:20","14:35"},
                                "puerto-cadiz":{"12:25"}})


if __name__=="__main__":
    unittest.main()
