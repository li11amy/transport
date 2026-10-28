# Horarios de transporte — El Puerto / Cádiz / Jerez

Live: https://li11amy.github.io/transport/

One production page: index.html (generated). The canonical generator is build_horarios.py in this repository.
It reads all six origin/destination timetable tables from https://siu.cmtbc.es and provides bus, train and ferry filters.

## Route and stop rules
- El Puerto de Santa María: Plaza de Toros is preferred for buses that stop there. Otherwise display the actual stop, normalizing «Estación FC» and «Intercambiador El Pto. de Sta. María» to Estación El Puerto; source stop names are retained in the generated data.
- Cádiz: «Plaza de Sevilla-Estación de Cádiz» displays as Estación de Cádiz.
- Jerez: bus trips must use Estación de Jerez, except M-352 from El Puerto, displayed at Plaza del Caballo. The M-352 time is approximate (≈), inferred from the published 7-minute offset from La Granja; it is not a verified official timetable at Plaza del Caballo.
- Day filters distinguish Monday–Thursday, Friday, Saturday and Sunday/holidays. Unknown codes are displayed in red, and diagnostics are sent to the configured Telegram chat.

## Daily deployment
On VPS vps-cd9917e0:
- Checkout: /home/ubuntu/Sites/transport
- Timer: transport-update.timer, 06:00 Europe/Berlin every day.
- Unit: transport-update.service; invokes /home/ubuntu/transport-updater/update_transport.sh as ubuntu.
- Script pulls GitHub main with fast-forward only, runs this repository's build_horarios.py, checks the generated output, copies it to index.html, then commits and pushes changes. GitHub Pages deploys from main.
- Generated HTML: /home/ubuntu/Sites/transport/output/horarios_tres_ciudades.html; ignored in Git.
- Diagnostic JSON and Telegram alert deduplication state: within output/, ignored in Git.
- Telegram credentials: /home/ubuntu/.config/transport-update.env via systemd; do not commit this file.

If a source table changes shape or a necessary stop is absent, the generator fails and does not overwrite index.html. An issue triggers Telegram reporting (the shell also reports a failed run). If the day code is unknown, the generator retains the trip in red and sends a warning once per unique set of issues.

To check manually (after checking host, working directory and git status):
    cd /home/ubuntu/Sites/transport
    python3 build_horarios.py
    systemctl status transport-update.timer --no-pager
    journalctl -u transport-update.service -n 30 --no-pager

Do not manually overwrite index.html without checking Git status.

## Backups
- Full pre-Jerez archive on workstation coredeus:
  /home/li11amy/Backups/Transport/transport_el_puerto_cadiz_BEFORE_JEREZ_2026-10-28.tar.gz
- Original VPS release files:
  /home/ubuntu/Backups/Transport/before_release_2026-10-28/

## Install on a phone as a PWA
- Installable app assets: manifest.json, sw.js, icon-180.png, icon-192.png, icon-512.png. All paths must retain the GitHub Pages project prefix `/transport/`.
- The canonical generator `build_horarios.py` includes the manifest link, install button and service-worker registration, so daily regenerated `index.html` retains PWA support.
- Android Chrome/Samsung Internet: open the website in Chrome, then use the native browser menu → Install app. The website does not intercept beforeinstallprompt or provide a custom install button; it lets Chrome own its install UI.
- iOS: Share → Add to Home Screen → Open as Web App; iOS does not support the programmatic install prompt.
- Service worker caches static icons and the last downloaded timetable. **Navigation is network-first**: while online, request the updated site; offline, fall back to the most recently saved timetable. The UI shows a warning when offline.
- To change the static cache, increment the cache version in `sw.js`.

Installability compatibility 2026-10-28: manifest is .json (GitHub Pages serves the JSON MIME type), 192/512 icon entries provide separate any and maskable purposes; route dropdown is drawn as a CSS chevron. After publishing, test from a fresh Chrome tab, not a messenger webview.

## PWA installability validation (2026-10-28)
A temporary GitHub Actions Chrome 156 check on the public site returned:
- Page.getAppManifest: no manifest errors; expected scope/start URL, icons and display=standalone.
- Page.getInstallabilityErrors: [] (no installability errors).
- Service worker: active and controlling /transport/; offline cache transport-bahia-v2 present.
- PNG images 192×192 and 512×512 decoded successfully in Chrome.
- On one Android device, Chrome nevertheless displayed "Esta aplicación no se puede instalar" in the "Instalar y crear acceso directo" sheet. This is an Android-specific unresolved issue; see Chromium 570202962 (fixed bug concerning that precise menu state). Diagnose Chrome/Android installation separately rather than repeatedly changing the manifest without evidence.

## Android installation fix — 2026-10-28
On the user's Android phone, Squoosh and Bottle Butler were installable but this site was not. We removed the custom beforeinstallprompt.preventDefault() handler and in-page installation button from both the generator and checked-in index.html to restore Chrome's native install flow. This is a targeted change; installation on the physical Android device still requires confirmation.


## Service changes (proposed, review before merging)

The timetable remains the **planned** source data from CMTBC. New
`transport_updates.py` checks the line-specific notices published by CMTBC
(including boat B-042), and the official Renfe GTFS-RT trip updates:
- Cercanías: https://gtfsrt.renfe.com/trip_updates.json
- Media Distancia/LD: https://gtfsrt.renfe.com/trip_updates_LD.json

**Yellow:** a fresh (<14 days) service-related notice for a bus/boat line. The
notice is not evidence that a particular departure is cancelled: all trips of
that line for *today* get a review marker, with the link to the source.
Notices about fares do not produce service flags.

**Green:** only when the Renfe realtime feed is fresh (<10 minutes) and
**both** station stop updates identify an exact, unambiguous scheduled CMTBC
train on today's date. The original times remain in `salida` / `llegada`;
the new times are in `salida_actual` / `llegada_actual`.
Unmatched trip IDs, one-station updates, and newly added trains without
matching schedule data are **not** automatically inserted. They require
a GTFS static trip-ID crosswalk before safe automatic adoption.

**Red:** confirmed cancelled endpoint/stop when a Renfe service can be
unambiguously matched, plus the existing unknown-calendar warnings.

Service markers apply only to the date of the update and the corresponding
day group in the UI. Rail corrections disappear from view when the generated
feed check is older than 45 minutes. Do not interpret an uncolored train as
confirmed on time. Missing or stale feeds leave the planned schedule intact;
diagnostics go to `output/service_change_report.json`.

Telegram uses the existing `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and
optional `TELEGRAM_TOPIC_ID`. Alerts are deduplicated in
`output/service_change_notifications.json`; no tokens or secrets are
committed. One bus news item generates one message for that line, not one
message per scheduled departure.

Tests (network-free):
```bash
python3 -m pip install requests beautifulsoup4
python3 -m unittest discover -s tests -v
python3 -m compileall -q build_horarios.py transport_updates.py
```

**Important:** the existing VPS timer only runs at 06:00, and GitHub Pages is
static. After reviewing and merging this branch into `main`, optionally
install the supplied timer override to check changes every 15 minutes:

```bash
cd /home/ubuntu/Sites/transport
sudo install -D -m 644 deploy/transport-update-interval.conf \
  /etc/systemd/system/transport-update.timer.d/override.conf
sudo systemctl daemon-reload
sudo systemctl restart transport-update.timer
systemctl list-timers transport-update.timer
```

This reuses the existing `transport-update.service` and update script.
Frequent runs may produce frequent GitHub Pages commits. No service
configuration or production site changes until the operator installs it.
