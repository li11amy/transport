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
- Installable app assets: manifest.webmanifest, sw.js, icon-180.png, icon-192.png, icon-512.png. All paths must retain the GitHub Pages project prefix `/transport/`.
- The canonical generator `build_horarios.py` includes the manifest link, install button and service-worker registration, so daily regenerated `index.html` retains PWA support.
- Android Chrome/Samsung Internet: menu → Install app, or the in-page Instalar app button when the browser presents installation.
- iOS: Share → Add to Home Screen → Open as Web App; iOS does not support the programmatic install prompt.
- Service worker caches static icons and the last downloaded timetable. **Navigation is network-first**: while online, request the updated site; offline, fall back to the most recently saved timetable. The UI shows a warning when offline.
- To change the static cache, increment the cache version in `sw.js`.
