"""On-demand private lookup has exact-identity and stale-feed safety."""
import importlib.machinery
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import telegram_train_check as q
from build_horarios import HTML

NOW = datetime(2026, 11, 1, 10, 20, tzinfo=ZoneInfo("Europe/Madrid"))
ROW = {
    "tipo": "tren", "linea": "C-1", "trip_id": "3104D36208C1",
    "fecha_servicio": "2026-11-01", "salida": "10:15", "llegada": "10:24",
    "dias": "D", "parada_salida": "Estación de Jerez", "parada_llegada": "Estación FC",
}
ROUTE = "jerez-puerto"
TRIP = q.encode_payload(ROUTE, ROW)


def feed(*, code=ROW["trip_id"], relationship="SCHEDULED", time_offset=0, stops=None):
    return {
        "header": {"timestamp": int(NOW.timestamp()) + time_offset},
        "entity": [{"tripUpdate": {
            "trip": {"tripId": code, "startDate": "20261101",
                     "scheduleRelationship": relationship},
            "stopTimeUpdate": [] if stops is None else stops,
        }}],
    }


def fake_index():
    return {"trips": {ROW["trip_id"]: {"service": "SUN",
            "stops": [
                {"stop_id": "51300", "seq": 1, "departure": "10:15:00",
                 "arrival": "10:15:00"},
                {"stop_id": "51400", "seq": 2, "arrival": "10:24:00",
                 "departure": "10:24:00"},
            ]}}}


class TelegramTrainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "data.json"
        self.file.write_text(json.dumps({"data": {ROUTE: [ROW]}}))
        self.index = fake_index()

    def lookup(self, realtime, now=NOW, payload=TRIP):
        with patch.object(q, "service_active", return_value=True):
            return q.query_train(
                payload, now=now, data_path=self.file,
                fetcher=lambda url: realtime,
                loader=lambda line, date: (self.index, None))

    def test_payload_is_unique_and_today_only(self):
        self.assertLessEqual(len(TRIP), 64)
        self.assertEqual(q.resolve_row(TRIP, {ROUTE:[ROW]}, NOW)[2], ROW)
        self.assertRaises(ValueError, q.resolve_row, TRIP,
                          {ROUTE:[ROW]}, NOW.replace(day=2))
        self.assertRaises(ValueError, q.resolve_row, TRIP,
                          {ROUTE:[ROW, dict(ROW)]}, NOW)
        self.assertRaises(ValueError, q.resolve_row,
                          TRIP.replace("1015", "1016"), {ROUTE:[ROW]}, NOW)

    def test_cancelled_exact_train_red(self):
        answer = self.lookup(feed(relationship="CANCELED"))
        self.assertIn("🔴", answer)
        self.assertIn("cancelado", answer)
        self.assertIn("10:15", answer)

    def test_skipped_endpoint_is_cancellation(self):
        answer = self.lookup(feed(stops=[
            {"stopId": "51400", "scheduleRelationship": "SKIPPED"}]))
        self.assertIn("🔴", answer)
        self.assertIn("parada", answer)

    def test_one_minute_change_yellow_with_exact_station(self):
        answer = self.lookup(feed(stops=[
            {"stopId": "51400", "arrival": {
                "time": int(NOW.replace(hour=10,minute=25).timestamp())}}]))
        self.assertIn("🟡", answer)
        self.assertIn("Llegada 10:25 (+1 min)", answer)

    def test_missing_trip_is_never_on_time(self):
        answer = self.lookup(feed(code="another-train"))
        self.assertIn("⚪", answer)
        self.assertIn("no publica ahora", answer)
        self.assertNotIn("puntual.", answer)

    def test_stale_feed_not_confirmed(self):
        answer = self.lookup(feed(relationship="CANCELED", time_offset=-660))
        self.assertIn("No se pudo verificar", answer)
        self.assertNotIn("🔴", answer)

    def test_invalid_segment_prediction_not_authoritative(self):
        answer = self.lookup(feed(stops=[
            {"stopId":"51300","departure":{
                "time": int(NOW.replace(hour=10,minute=26).timestamp())}}]))
        self.assertIn("🟡", answer)
        self.assertIn("incoherentes", answer)

    def test_wrong_date_or_malformed_payload_fails_closed(self):
        answer = self.lookup(feed(), payload=TRIP.replace("20261101", "20261102"))
        self.assertIn("No se puede comprobar", answer)
        answer = self.lookup(feed(), payload="r_20261101_other")
        self.assertIn("No se puede comprobar", answer)

    def test_public_html_contains_rail_button_without_recoloring(self):
        loader=importlib.machinery.SourceFileLoader(
            "train_patch", "deploy/patch-train-telegram.py")
        module=loader.load_module()
        patched=module.patch(HTML)
        self.assertEqual(module.patch(patched),patched)
        self.assertIn('https://t.me/Alarma_cmtbc_bot?start=', patched)
        self.assertIn('className="trip-extra-main"', patched)
        self.assertIn('aria-label","Comprobar tren en Telegram"', patched)
        self.assertIn('data-icon="message-circle"', patched)
        self.assertIn('className="trip-extra-content"', patched)
        self.assertIn('className="trip-source-link"', patched)
        self.assertIn('content.appendChild(source)', patched)
        self.assertNotIn('details.appendChild(source)', patched)
        self.assertIn('.trip-extra .trip-source-link{display:block;margin:0', patched)
        self.assertIn('stroke:currentColor', patched)
        self.assertNotIn('#229ed9', patched)
        previous = patched.replace(module.COMPACT_DETAILS_TAIL, module.CURRENT_DETAILS_TAIL).replace(
            module.COMPACT_DETAILS_CSS, module.CURRENT_DETAILS_CSS)
        self.assertNotEqual(previous, patched)
        self.assertEqual(module.patch(previous), patched)
        circle = previous.replace(module.LINK_REPLACEMENT, module.CIRCLE_LINK_REPLACEMENT).replace(
            module.CSS_REPLACEMENT, module.CIRCLE_CSS_REPLACEMENT)
        self.assertNotEqual(circle, patched)
        self.assertEqual(module.patch(circle), patched)
        self.assertNotIn('↗ Comprobar ahora en Telegram', patched)
        legacy = previous.replace(module.LINK_REPLACEMENT, module.LEGACY_LINK_REPLACEMENT).replace(
            module.CSS_REPLACEMENT, module.LEGACY_CSS_REPLACEMENT)
        self.assertNotEqual(legacy, patched)
        self.assertEqual(module.patch(legacy), patched)
        self.assertEqual(patched.count('details.appendChild(main);'), 1)
        self.assertIn('if(marked||trainCheck)',patched)
        self.assertIn('const marked=Boolean(status||t.aviso)',patched)
        self.assertIn('if(cancelled) tr.classList.add("service-cancelled")',patched)
        self.assertIn('else if(marked) tr.classList.add("service-warning")',patched)
        self.assertIn('target="_blank"',patched)
        # unmarked train row is clickable but stays white
        self.assertIn('const cancelled=status==="cancelled"',patched)

    def test_polling_handles_private_request_and_callback_only(self):
        answers = []
        class Session:
            def post(self, url, data=None, timeout=None):
                answers.append((url.rsplit("/",1)[-1],data))
                fake=Mock(status_code=200, text='{"ok":true}')
                fake.raise_for_status.return_value=None
                fake.json.return_value={"ok":True}
                return fake
        session=Session()
        with patch.object(q,"query_train",return_value="Tested status"):
            q.handle_update(
                {"message":{"chat":{"type":"private","id":123}, "text":"/start "+TRIP}},
                "fake-token", session, {}, {})
            self.assertEqual(answers[-1][0],"sendMessage")
            self.assertEqual(json.loads(answers[-1][1]["reply_markup"])["inline_keyboard"][0][0]["text"],"🔄 Comprobar otra vez")
            q.handle_update(
                {"message":{"chat":{"type":"group","id":432}, "text":"/start "+TRIP}},
                "fake-token", session, {}, {})
            self.assertEqual(len(answers),1)


if __name__ == "__main__":
    unittest.main()
