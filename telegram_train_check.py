"""On-demand, private Telegram lookup for an exact Renfe train/segment.

No website POST endpoint, webhook or train timetable mutations. The bot's
existing outgoing alerts are independent of this read-only polling service.
"""
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from transport_updates import (
    RENFE, STATIONS, _coherent_segment_times, _hhmm, _passenger_rail_times,
    _prediction, _unusable_prediction, date_now, fetch_json, fresh_feed,
    static_trip_matches,
)
from renfe_static_gtfs import load_index, service_active

MADRID = ZoneInfo("Europe/Madrid")
PUBLIC_DATA = Path("/srv/www/transport/transport_data.json")
OFFSET_FILE = Path(__file__).parent / "output" / "telegram_train_check_offset.json"
BOT_NAME = "Alarma_cmtbc_bot"
ROUTES = {
    "pc": ("puerto-cadiz", "El Puerto → Cádiz"),
    "pj": ("puerto-jerez", "El Puerto → Jerez"),
    "cp": ("cadiz-puerto", "Cádiz → El Puerto"),
    "cj": ("cadiz-jerez", "Cádiz → Jerez"),
    "jp": ("jerez-puerto", "Jerez → El Puerto"),
    "jc": ("jerez-cadiz", "Jerez → Cádiz"),
}
PAYLOAD = re.compile(r"^r_(\d{8})_(pc|pj|cp|cj|jp|jc)_(C1|MD)_([A-Za-z0-9-]{5,32})_(\d{4})$")


def encode_payload(route, trip):
    """Mirrors the static PWA's Telegram deep-link encoding."""
    code = next((key for key, info in ROUTES.items() if info[0] == route), None)
    line = {"C-1": "C1", "MD": "MD"}.get(trip.get("linea"))
    date = str(trip.get("fecha_servicio") or "").replace("-", "")
    departure = str(trip.get("salida") or "").replace(":", "")
    result = "r_{}_{}_{}_{}_{}".format(
        date, code, line, trip.get("trip_id") or "", departure)
    if code is None or line is None or len(result) > 64 or not PAYLOAD.fullmatch(result):
        raise ValueError("Train lacks a unique Telegram deep-link identity")
    return result


def resolve_row(payload, data, now):
    """Allow only today's unique, public GTFS-backed trip with exact identity."""
    match = PAYLOAD.fullmatch(str(payload or ""))
    if not match:
        raise ValueError("invalid link")
    date, short, line, trip_id, departure = match.groups()
    if date != now.strftime("%Y%m%d"):
        raise ValueError("not today")
    route, label = ROUTES[short]
    line = "C-1" if line == "C1" else "MD"
    rows = [
        row for row in data.get(route, [])
        if row.get("tipo") == "tren" and row.get("linea") == line
        and row.get("trip_id") == trip_id
        and row.get("fecha_servicio") == now.date().isoformat()
        and row.get("salida", "").replace(":", "") == departure
    ]
    if len(rows) != 1:
        raise ValueError("not an unambiguous published train")
    return route, label, rows[0]


def evaluate_live(route, row, now, feed, index):
    """Only the exact GTFS trip and endpoint station updates can assert changes."""
    line = row["linea"]
    trip_id = row["trip_id"]
    if not fresh_feed(feed, now):
        raise ValueError("Renfe realtime feed is stale")
    static = index.get("trips", {}).get(trip_id)
    if not static or not service_active(index, trip_id, now.date()):
        raise ValueError("No verified static Renfe service for this date")
    matching = static_trip_matches({route: [row]}, line, static, now, trip_id)
    if len(matching) != 1:
        raise ValueError("Source and published trip identity do not agree")
    _, _, first, last = matching[0]
    matches = []
    for entity in feed.get("entity", []):
        update = entity.get("tripUpdate") if isinstance(entity, dict) else None
        if not isinstance(update, dict):
            continue
        descriptor = update.get("trip") or {}
        if descriptor.get("tripId") != trip_id:
            continue
        if descriptor.get("startDate") and descriptor["startDate"] != now.strftime("%Y%m%d"):
            continue
        matches.append(update)
    if len(matches) > 1:
        raise ValueError("Multiple conflicting realtime records for this train")
    if not matches:
        return "none", "Renfe no publica ahora una actualización específica de este tren."
    update = matches[0]
    relationship = (update.get("trip") or {}).get("scheduleRelationship", "SCHEDULED")
    if relationship == "CANCELED":
        return "cancelled", "Renfe indica que este tren está cancelado."
    if relationship != "SCHEDULED":
        return "unknown", "Renfe publica un estado especial que no permite confirmar el servicio."
    updates = [x for x in update.get("stopTimeUpdate", []) if isinstance(x, dict)]
    by_stop = {str(x.get("stopId")): x for x in updates if x.get("stopId")}
    start = by_stop.get(first["stop_id"])
    finish = by_stop.get(last["stop_id"])
    if any(x and x.get("scheduleRelationship") == "SKIPPED" for x in (start, finish)):
        return "cancelled", "Renfe indica que se ha suprimido una parada del trayecto."
    departure = _prediction(start, "departure", _hhmm(first["departure"]), now)
    arrival = _prediction(finish, "arrival", _hhmm(last["arrival"]), now)
    if (_unusable_prediction(start, "departure", departure)
            or _unusable_prediction(finish, "arrival", arrival)
            or ((departure or arrival) and not _coherent_segment_times(
                row["salida"], row["llegada"], departure, arrival))):
        return "warning", "Renfe comunica horarios incoherentes; no se muestran como confirmados."
    changes = (departure is not None and departure != row["salida"]) or (
        arrival is not None and arrival != row["llegada"])
    if changes:
        return "changed", _passenger_rail_times(
            row["salida"], row["llegada"],
            departure if departure != row["salida"] else None,
            arrival if arrival != row["llegada"] else None)
    return "unknown", (
        "No hay cambios verificables para las estaciones de este trayecto. "
        "Eso no confirma que el tren vaya puntual.")


def query_train(payload, now=None, data_path=PUBLIC_DATA, fetcher=fetch_json, loader=load_index):
    now = date_now(now)
    try:
        if not data_path.is_file():
            raise ValueError("Published timetable unavailable")
        data = json.loads(data_path.read_text(encoding="utf-8")).get("data", {})
        route, label, row = resolve_row(payload, data, now)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return "No se puede comprobar este enlace. Abre un tren de hoy en la web y vuelve a intentarlo."

    header = "🚆 {} · {}\nHorario: salida {} · llegada {}".format(
        row["linea"], label, row["salida"], row["llegada"])
    try:
        feed = fetcher(RENFE[row["linea"]])
        index, _ = loader(row["linea"], now)
        level, detail = evaluate_live(route, row, now, feed, index)
        checked = datetime.fromtimestamp(int(feed["header"]["timestamp"]), MADRID)
        tail = "Fuente: Renfe GTFS Realtime · {}".format(checked.strftime("%H:%M:%S"))
        if level == "cancelled":
            status = "🔴 Cancelado / parada suprimida"
        elif level in ("warning", "changed"):
            status = "🟡 Cambio / incidencia"
        else:
            status = "⚪ Sin confirmación de puntualidad"
        return "{}\n\n{}\n{}\n{}\nComprobado: {}".format(
            header, status, detail, tail.rstrip("."), now.strftime("%H:%M:%S"))
    except (requests.RequestException, ValueError, TypeError, KeyError, OSError) as exc:
        # Never publish stale/ambiguous status as on-time or leak URLs containing bot token.
        return "{}\n\n⚪ No se pudo verificar en Renfe ahora.\nNo significa que circule puntual.\nComprobado: {}".format(
            header, now.strftime("%H:%M:%S"))


def load_offset(path=OFFSET_FILE):
    try:
        value = int(json.loads(path.read_text(encoding="utf-8")).get("offset", 0))
        return max(0, value)
    except (OSError, ValueError, TypeError, AttributeError):
        return 0


def store_offset(value, path=OFFSET_FILE):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"offset": value}), encoding="utf-8")
    os.replace(tmp, path)


def handle_update(update, token, session, checked_at, cache, now=None):
    """Handle private deep links; never send public/group replies."""
    message = update.get("message")
    callback = update.get("callback_query")
    if not isinstance(message, dict) and not isinstance(callback, dict):
        return
    chat = (message or (callback.get("message") if callback else None) or {}).get("chat") or {}
    if chat.get("type") != "private":
        return
    chat_id = chat.get("id")
    if not isinstance(chat_id, int):
        return
    if callback:
        content = callback.get("data", "")
        try:
            session.post(
                "https://api.telegram.org/bot{}/answerCallbackQuery".format(token),
                data={"callback_query_id": callback["id"]}, timeout=10).raise_for_status()
        except (requests.RequestException, KeyError):
            pass
    else:
        content = (message.get("text") or "").strip()
        if not content.startswith("/start"):
            return
        pieces = content.split(maxsplit=1)
        content = pieces[1] if len(pieces) == 2 else ""
    current = time.monotonic()
    if content and PAYLOAD.fullmatch(content):
        previous = checked_at.get(chat_id, -1000)
        if current - previous < 4:
            reply = "Espera unos segundos antes de otra comprobación."
        else:
            checked_at[chat_id] = current
            stored = cache.get(content)
            if stored and current - stored[0] < 20:
                reply = stored[1]
            else:
                reply = query_train(content, now=now)
                cache[content] = (current, reply)
        markup = json.dumps({
            "inline_keyboard": [[{
                "text": "🔄 Comprobar otra vez", "callback_data": content
            }]]
        })
    else:
        reply = "Para consultar un tren, abre su ficha de hoy en la web y pulsa «Comprobar en Telegram»."
        markup = None

    params = {"chat_id": chat_id, "text": reply,
              "link_preview_options": json.dumps({"is_disabled": True})}
    if markup:
        params["reply_markup"] = markup
    if callback and isinstance(callback.get("message"), dict):
        params["message_id"] = callback["message"]["message_id"]
        method = "editMessageText"
    else:
        method = "sendMessage"
    response = session.post(
        "https://api.telegram.org/bot{}/{}".format(token, method),
        data=params, timeout=20)
    if response.status_code == 400 and callback and "message is not modified" in response.text:
        return
    response.raise_for_status()
    if not response.json().get("ok"):
        raise ValueError("Telegram rejected the reply")


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("No Telegram bot token configured")
    session = requests.Session()
    status = session.post("https://api.telegram.org/bot{}/getWebhookInfo".format(token),
                          timeout=12).json()
    if not status.get("ok") or status["result"].get("url"):
        raise RuntimeError("Telegram webhook active or unavailable; refusing polling")
    checked_at, cache = {}, {}
    print("Private train checker started", flush=True)
    while True:
        try:
            params = {"offset": load_offset(), "timeout": 25, "limit": 15,
                      "allowed_updates": json.dumps(["message", "callback_query"])}
            response = session.post(
                "https://api.telegram.org/bot{}/getUpdates".format(token),
                data=params, timeout=(10, 36))
            response.raise_for_status()
            result = response.json()
            if not result.get("ok"):
                raise ValueError("Telegram updates refused")
            for update in result.get("result", []):
                handle_update(update, token, session, checked_at, cache)
                store_offset(int(update["update_id"]) + 1)
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            print("Private train checker polling error: {}".format(type(exc).__name__), flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
