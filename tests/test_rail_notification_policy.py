"""Regression: Telegram noise controls do not hide verified timetable changes."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import transport_updates as updates
from rail_notifications import (
    meaningful_departure, meaningful_arrival, merge_trips,
    deserves_repeat, sent_record, format_batch, legacy_rail_sent,
)

TZ=ZoneInfo("Europe/Madrid")
NOW=datetime(2026,10,30,15,30,tzinfo=TZ)


def sample(route, arrival_delta=6, departure_delta=0, kind="timing",
           finished=False):
    origin,dest=route.split("-")
    starts={"cadiz":1,"puerto":2,"jerez":3}
    departure={"cadiz":"14:25","puerto":"15:13","jerez":"16:30"}[origin]
    checks=[]
    if arrival_delta:
        checks.append({"city":"jerez","kind":"Llegada",
                       "time":"15:{:02d}".format(23+arrival_delta),
                       "delta":arrival_delta})
    if departure_delta:
        checks.append({"city":origin,"kind":"Salida","time":departure,
                       "delta":departure_delta})
    metrics={"dep_late":max(departure_delta,0),
             "dep_early":max(-departure_delta,0),
             "arr_late":max(arrival_delta,0),
             "arr_early":max(-arrival_delta,0),"uncertain":0}
    return {
        "id":"rail:2026-10-30:C-1:THE_SAME_TRAIN",
        "trip_id":"THE_SAME_TRAIN",
        "route":route,"line":"C-1",
        "date":"2026-10-30","detail":"Renfe",
        "source":updates.RENFE["C-1"],"kind":kind,
        "latest_end":NOW-timedelta(hours=2) if finished else NOW+timedelta(minutes=24),
        "segment":{"origin":origin,"destination":dest,
                   "first_seq":starts[origin],"last_seq":starts[dest],
                   "planned_departure":departure},
        "checks":checks,"metrics":metrics,
    }


class RenfeSpamTests(unittest.TestCase):
    def test_exact_cutoffs_and_earlier_departure(self):
        self.assertFalse(meaningful_departure(1))
        self.assertFalse(meaningful_departure(5))
        self.assertTrue(meaningful_departure(6))
        self.assertTrue(meaningful_departure(-1))
        for delta in range(-5,6):
            self.assertFalse(meaningful_arrival(delta))
        self.assertTrue(meaningful_arrival(-6))
        self.assertTrue(meaningful_arrival(6))

    def test_same_train_on_two_routes_is_one_alert(self):
        merged=merge_trips([sample("cadiz-jerez"),sample("puerto-jerez")],NOW)
        self.assertEqual(len(merged),1)
        train=merged[0]
        self.assertEqual(train["route"],"cadiz-jerez")
        self.assertEqual(len(train["checks"]),1)
        self.assertEqual(train["detail"],
            "Renfe · Llegada Jerez 15:29 (+6 min)")
        self.assertEqual(train["metrics"]["arr_late"],6)
        json.dumps(train)  # No raw datetime allowed in report file.
        msg=format_batch(merged)
        self.assertEqual(msg.count("C-1"),1)
        self.assertIn("Cádiz → Jerez",msg)

    def test_no_alert_for_finished_train(self):
        self.assertEqual(merge_trips([sample("cadiz-jerez",finished=True)],NOW),[])

    def test_repeat_only_if_materially_worse(self):
        first=merge_trips([sample("cadiz-jerez")],NOW)[0]
        previous=sent_record(first,NOW)
        for drift in (6,7,10,15):
            newer=merge_trips([sample("cadiz-jerez",arrival_delta=drift)],NOW)[0]
            self.assertFalse(deserves_repeat(newer,previous))
        worse=merge_trips([sample("cadiz-jerez",arrival_delta=16)],NOW)[0]
        self.assertTrue(deserves_repeat(worse,previous))

    def test_new_earlier_departure_is_urgent(self):
        original=merge_trips([sample("cadiz-jerez")],NOW)[0]
        earlier=merge_trips([sample("cadiz-jerez",departure_delta=-1)],NOW)[0]
        self.assertTrue(deserves_repeat(earlier,sent_record(original,NOW)))

    def test_legacy_per_route_id_does_not_trigger_duplicate(self):
        new=merge_trips([sample("cadiz-jerez")],NOW)[0]
        old_ids={"rail:2026-10-30:cadiz-jerez:THE_SAME_TRAIN":"old_hash",
                 "rail:2026-10-30:puerto-jerez:THE_SAME_TRAIN":"old_hash"}
        self.assertTrue(legacy_rail_sent(old_ids,new))

    def test_notify_batch_once_then_suppresses_1_to_9_minute_jitter(self):
        messages=[]
        with tempfile.TemporaryDirectory() as td:
            with patch.object(updates,"STATE_FILE",Path(td)/"sent.json"):
                first=merge_trips([sample("cadiz-jerez"),sample("puerto-jerez")],NOW)
                updates.notify_events(first,lambda x:messages.append(x) or True,NOW)
                self.assertEqual(len(messages),1)
                repeat=merge_trips([sample("cadiz-jerez",arrival_delta=9)],NOW)
                updates.notify_events(repeat,lambda x:messages.append(x) or True,NOW)
                self.assertEqual(len(messages),1)
                worse=merge_trips([sample("cadiz-jerez",arrival_delta=16)],NOW)
                updates.notify_events(worse,lambda x:messages.append(x) or True,NOW)
                self.assertEqual(len(messages),2)

    def test_failed_send_does_not_mark_as_sent(self):
        messages=[]
        with tempfile.TemporaryDirectory() as td:
            with patch.object(updates,"STATE_FILE",Path(td)/"sent.json"):
                event=merge_trips([sample("cadiz-jerez")],NOW)
                updates.notify_events(event,lambda x:False,NOW)
                updates.notify_events(event,lambda x:messages.append(x) or True,NOW)
                self.assertEqual(len(messages),1)

    def test_cancellation_still_notifies_if_minor_delays_were_ignored(self):
        prev=merge_trips([sample("cadiz-jerez")],NOW)[0]
        cancelled=merge_trips([sample("cadiz-jerez",kind="cancelled")],NOW)[0]
        self.assertTrue(deserves_repeat(cancelled,sent_record(prev,NOW)))


if __name__=="__main__":
    unittest.main()
