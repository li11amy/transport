"""Published JSON can be repaired without another GTFS fetch."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("sanitize_impossible_renfe",
                                           BASE/"deploy"/"sanitize-impossible-renfe.py")
module=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class SanitizeTests(unittest.TestCase):
    def payload(self):
        return {
            "meta":{"date":"2026-10-30","checked_at":"2026-10-30T17:45:00+01:00"},
            "data":{
                "cadiz-puerto":[
                    {"tipo":"tren","linea":"MD","trip_id":"1301722026-10-30",
                     "salida":"17:24","llegada":"17:48",
                     "llegada_actual":"16:38","estado":"confirmed",
                     "detalle":"Renfe · Salida 17:24 · Llegada 16:38 (-70 min)"},
                    {"tipo":"tren","linea":"C-1","trip_id":"valid",
                     "salida":"14:00","llegada":"14:28",
                     "llegada_actual":"14:34","estado":"confirmed"},
                    {"tipo":"tren","linea":"MD","trip_id":"cancelled",
                     "salida":"16:00","llegada":"16:30",
                     "llegada_actual":"15:10","estado":"cancelled"},
                ],
                "puerto-cadiz":[],"cadiz-jerez":[],"jerez-cadiz":[],
                "jerez-puerto":[],"puerto-jerez":[]
            }
        }

    def test_impossible_forecast_sanitized_but_cancellations_preserved(self):
        data=self.payload()
        result=module.sanitize(data)
        self.assertEqual(result,[("cadiz-puerto","1301722026-10-30","16:38")])
        invalid=data["data"]["cadiz-puerto"][0]
        self.assertEqual(invalid["estado"],"warning")
        self.assertNotIn("llegada_actual",invalid)
        self.assertEqual(invalid["llegada"],"17:48")
        self.assertIn("incoherente",invalid["detalle"])
        self.assertEqual(data["data"]["cadiz-puerto"][1]["llegada_actual"],"14:34")
        self.assertEqual(data["data"]["cadiz-puerto"][2]["estado"],"cancelled")
        self.assertEqual(data["data"]["cadiz-puerto"][2]["llegada_actual"],"15:10")
        self.assertEqual(module.sanitize(data),[])

    def test_keep_valid_origin_change_and_warning_for_bad_destination(self):
        data=self.payload()
        row=data["data"]["cadiz-puerto"][0]
        row["salida_actual"]="17:30"
        module.sanitize(data)
        self.assertEqual(row["estado"],"confirmed")
        self.assertIn("17:30 (+6 min)",row["detalle"])
        self.assertNotIn("llegada_actual",row)

    def test_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"live.json"
            content=self.payload()
            module.sanitize(content)
            module.save_atomically(path,content)
            result=json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("llegada_actual",result["data"]["cadiz-puerto"][0])


if __name__=="__main__":
    unittest.main()
