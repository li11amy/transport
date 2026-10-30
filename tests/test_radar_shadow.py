"""No RadarDeTrenes board may override our train timetable automatically."""
import copy
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch
import tempfile
import transport_updates as updates

import radar_shadow as radar

TZ=ZoneInfo("Europe/Madrid")
NOW=datetime(2026,10,30,17,0,tzinfo=TZ)
DAY=NOW.date().isoformat()


def epoch(hour, minute):
    return int(datetime(2026,10,30,hour,minute,tzinfo=TZ).timestamp()*1000)


def trip(code="13031", departure="17:10", arrival="17:38",
         actual=None, trip_date=DAY):
    row = {
        "tipo": "tren", "linea": "MD", "trip_id": code+"2"+trip_date,
        "fecha_servicio": trip_date,
        "salida": departure, "llegada": arrival,
    }
    if actual is not None:
        row["llegada_actual"] = actual
    return row


def board(station, departures=None, arrivals=None, fresh=True,
          source="renfe_official"):
    return {
        "source": source,
        "mode": "estimated",
        "updatedAt": epoch(16,59) if fresh else epoch(14,0),
        "departures": departures or [],
        "arrivals": arrivals or [],
    }


def entry(station, code, hh, mm, delta=0):
    return {
        "stationCode": station, "trainCode": code,
        "plannedTime": epoch(hh,mm),
        "delayMinutes": delta, "timeType":"ESTIMATED",
        "commercialProduct":"MD",
        "timestamp":epoch(16,59),
    }


class Resp:
    def __init__(self,value):
        self.value=value
    def raise_for_status(self): pass
    def json(self): return self.value


class HTTP:
    def __init__(self, mapping):
        self.mapping=mapping
        self.requests=[]
    def get(self,url,timeout,headers):
        self.requests.append((url,timeout,headers))
        value=self.mapping.get(url)
        if isinstance(value,Exception):
            raise value
        if value is None:
            raise ValueError("No fixture for "+url)
        return Resp(value)


def urls():
    return {station:radar.BASE.format(station) for station in radar.STATIONS.values()}


class RadarShadowTests(unittest.TestCase):
    def test_live_three_station_fixture_only_md_and_exact_matching(self):
        data={"cadiz-puerto":[trip(actual="17:50")],
              "cadiz-jerez":[trip(arrival="18:03")]}
        before=copy.deepcopy(data)
        u=urls()
        h=HTTP({
            u["51405"]:board("51405",departures=[
                entry("51405","13031",17,10,0),
                entry("51405","13099",17,10,3), # not our train
            ]),
            u["51400"]:board("51400",arrivals=[
                entry("51400","13031",17,38,0),  # GTFS +12 vs board 0
                entry("51400","13031",17,39,0),  # +1 planned != exact
            ]),
            u["51300"]:board("51300",arrivals=[
                entry("51300","13031",18,3,0)]),
        })
        result=radar.compare_station_boards(data,NOW,session=h)
        self.assertEqual(result["status"],"available")
        self.assertEqual(result["matched"],3)
        self.assertEqual(result["conflicts"],1)
        self.assertEqual(result["examples"][0]["renfe_gtfs_delay"],12)
        self.assertEqual(result["examples"][0]["radar_board_delay"],0)
        self.assertEqual(result["conflict_details"][0]["trip_id"],"1303122026-10-30")
        self.assertEqual(result["conflict_details"][0]["city"],"puerto")
        self.assertEqual(result["conflict_details"][0]["gtfs_time"],"17:50")
        self.assertEqual(result["conflict_details"][0]["radar_time"],"17:38")
        self.assertFalse(result["conflict_details"][0]["independent_adif"])
        self.assertEqual(result["requested"],3)
        self.assertEqual(result["source"],"renfe_official")
        self.assertFalse(result["independent_adif"])
        self.assertEqual(data,before)
        self.assertTrue(all(timeout==6 for _,timeout,_ in h.requests))

    def test_exact_identifiers_prevent_false_matches(self):
        key=radar._train_code("1303122026-10-30",DAY)
        self.assertEqual(key,"13031")
        self.assertIsNone(radar._train_code("1303122026-10-29",DAY))
        self.assertIsNone(radar._train_code("RENFE_TEST",DAY))
        self.assertIsNone(radar._train_code("1303102026-10-30wrong",DAY))
        self.assertEqual(radar._train_code("3102V23200C1",DAY,"C-1"),"23200")
        self.assertIsNone(radar._train_code("3102V23200C1",DAY,"MD"))
        self.assertIsNone(radar._train_code("3102V23200C2",DAY,"C-1"))

    def test_stale_and_mislabeled_provider_cannot_verify(self):
        u=urls()
        h=HTTP({
            u["51405"]:board("51405",fresh=False),
            u["51400"]:board("51400",source="adif"),
            u["51300"]:board("51300",departures=[
                entry("51300","13031",17,10,0)
            ]),
        })
        result=radar.compare_station_boards(
            {"cadiz-puerto":[trip()]},NOW,session=h)
        self.assertEqual(result["status"],"partial")
        self.assertEqual(result["healthy"],1)
        self.assertEqual(len(result["problems"]),2)
        self.assertFalse(result["independent_adif"])

    def test_c1_real_gtfs_trip_id_joins_exact_train_and_station(self):
        c1=trip(actual="17:47")
        c1["linea"]="C-1"
        c1["trip_id"]="3102V23200C1"
        data={"cadiz-puerto":[c1]}
        u=urls()
        h=HTTP({
            u["51405"]:board("51405"),
            u["51400"]:board("51400",arrivals=[
                entry("51400","23200",17,38,0),
                entry("51400","23201",17,38,0),
            ]),
            u["51300"]:board("51300"),
        })
        result=radar.compare_station_boards(data,NOW,session=h)
        self.assertEqual(result["matched"],1)
        self.assertEqual(result["conflicts"],1)
        self.assertEqual(result["conflict_details"][0]["trip_id"],"3102V23200C1")
        self.assertEqual(result["conflict_details"][0]["difference_minutes"],9)

    def test_scheduled_only_is_not_a_false_conflict(self):
        u=urls()
        stale_scheduled=entry("51400","13031",17,38,0)
        stale_scheduled["timeType"]="SCHEDULED"
        response=radar.compare_station_boards(
            {"cadiz-puerto":[trip(actual="17:50")]}, NOW,
            session=HTTP({
                u["51405"]:board("51405"),
                u["51400"]:board("51400",arrivals=[stale_scheduled]),
                u["51300"]:board("51300"),
            }))
        self.assertEqual(response["conflicts"],0)
        self.assertEqual(response["conflict_details"],[])

    def test_stale_individual_row_is_not_rescued_by_fresh_board(self):
        u=urls()
        old=entry("51400","13031",17,38,0)
        old["timestamp"]=epoch(16,30)
        response=radar.compare_station_boards(
            {"cadiz-puerto":[trip(actual="17:50")]}, NOW,
            session=HTTP({
                u["51405"]:board("51405"),
                u["51400"]:board("51400",arrivals=[old]),
                u["51300"]:board("51300"),
            }))
        self.assertEqual(response["matched"],0)
        self.assertEqual(response["conflict_details"],[])

    def test_only_matching_md_alert_gets_comparison_no_extra_telegram(self):
        from rail_notifications import format_batch
        row={"id":"rail:2026-10-30:MD:1303122026-10-30",
             "trip_id":"1303122026-10-30","route":"cadiz-puerto",
             "line":"MD","date":DAY,"kind":"timing",
             "detail":"Renfe · Llegada El Puerto 17:50 (+12 min)",
             "source":updates.RENFE["MD"],
             "latest_end":NOW+timedelta(minutes=50),
             "segment":{"origin":"cadiz","destination":"puerto",
                        "first_seq":1,"last_seq":2,"planned_departure":"17:10"},
             "checks":[{"city":"puerto","kind":"Llegada","time":"17:50","delta":12}],
             "metrics":{"dep_late":0,"dep_early":0,"arr_late":12,
                        "arr_early":0,"uncertain":0}}
        cross={"trip_id":"1303122026-10-30","station":"51400",
               "city":"puerto","event":"arrivals","scheduled":"17:38",
               "gtfs_time":"17:50","radar_time":"17:38",
               "difference_minutes":12,
               "secondary_source":"RadarDeTrenes (datos Renfe)",
               "independent_adif":False}
        report={"mode":"shadow_only","status":"available","conflict_details":[cross],
                "independent_adif":False}
        with tempfile.TemporaryDirectory() as folder:
            report_path=__import__("pathlib").Path(folder)/"report.json"
            with patch.object(updates,"REPORT_FILE",report_path), \
                 patch("transport_updates.rail_changes",return_value=([row],[])), \
                 patch("transport_updates.bus_notices",return_value=([],[])), \
                 patch("maritime_status.live_maritime_changes",return_value=([],[])), \
                 patch("source_alerts.apply_source_alerts",return_value=([],[])), \
                 patch("transport_updates.notify_events") as notify, \
                 patch("radar_shadow.compare_station_boards",return_value=report):
                data={"cadiz-puerto":[trip(actual="17:50")]}
                before=copy.deepcopy(data)
                updates.apply_changes(data,lambda message:True,now=NOW)
                notify.assert_called_once()
                alerts=notify.call_args.args[0]
                self.assertEqual(len(alerts),1)
                text=format_batch(alerts)
                self.assertIn("GTFS Renfe 17:50",text)
                self.assertIn("RadarDeTrenes (tablero Renfe) 17:38",text)
                self.assertIn("No es confirmación independiente de ADIF",text)
                self.assertIn("https://radardetrenes.com/estacion/el-puerto-de-santamaria",text)
                self.assertEqual(data,before)

    def test_no_train_in_short_window_is_not_cancelled(self):
        u=urls()
        h=HTTP({url:board(station) for station,url in u.items()})
        result=radar.compare_station_boards(
            {"cadiz-puerto":[trip()]},NOW,session=h)
        self.assertEqual(result["matched"],0)
        self.assertEqual(result["conflicts"],0)
        self.assertEqual(result["status"],"available")
        self.assertNotIn("cancelled",str(result).lower())

    def test_no_current_supported_trips_makes_no_network_calls(self):
        h=HTTP({})
        rows={"cadiz-puerto":[trip(trip_date="2026-11-02")]}
        result=radar.compare_station_boards(rows,NOW,session=h)
        self.assertEqual(result["requested"],0)
        self.assertEqual(result["status"],"no_today_supported_trips")
        self.assertEqual(h.requests,[])

    def test_integrated_live_refresh_reports_observer_without_publishing_it(self):
        with tempfile.TemporaryDirectory() as folder:
            report_path=__import__("pathlib").Path(folder)/"report.json"
            rows={"cadiz-puerto":[trip()]}
            original=copy.deepcopy(rows)
            summary={"mode":"shadow_only","status":"available",
                     "independent_adif":False,"matched":1,"conflicts":0}
            with patch.object(updates,"REPORT_FILE",report_path), \
                 patch("transport_updates.rail_changes",return_value=([],[])), \
                 patch("transport_updates.bus_notices",return_value=([],[])), \
                 patch("maritime_status.live_maritime_changes",return_value=([],[])), \
                 patch("source_alerts.apply_source_alerts",return_value=([],[])), \
                 patch("transport_updates.notify_events") as notify, \
                 patch("radar_shadow.compare_station_boards",return_value=summary) as observe:
                meta=updates.apply_changes(rows,lambda message:True,now=NOW)
                observe.assert_called_once()
                self.assertEqual(rows,original)
                self.assertEqual(meta["changes"],0)
                notify.assert_called_once()
                self.assertEqual(notify.call_args.args[0],[])
                saved=__import__("json").loads(report_path.read_text())
                self.assertEqual(saved["sources"]["RADAR"],summary)
                self.assertNotIn("RADAR",meta)

    def test_midnight_and_local_date(self):
        self.assertEqual(radar._clock(epoch(17,10)),(DAY,"17:10"))
        self.assertEqual(radar._minutes("23:58","00:02"),4)
        self.assertEqual(radar._minutes("17:38","16:38"),-60)


if __name__=="__main__":
    unittest.main()
