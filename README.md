# Horarios de transporte — El Puerto · Cádiz · Jerez

> **Current production architecture (29 October 2026).** The sections under
> **Historical deployment and migration notes** are retained for context and
> may contain obsolete commands. Use this section and the live deployment
> scripts as the source of truth. Do not publish schedules from GitHub Pages.

## Public URLs and repository roles

| URL | Role |
| --- | --- |
| **https://transport.peluche-ebanache.com/** | **Primary production timetable and root-scoped PWA** |
| https://peluche-ebanache.com/transport/ | Working fallback path-scoped PWA on the same VPS |
| https://li11amy.github.io/transport/ | Retired GitHub Pages URL; **client-side redirect** to the primary host, not an independent schedule |
| https://github.com/li11amy/transport | Source code, tests, history, maintenance |

GitHub Pages does not support an HTTP 301 from a project repository.
`main/index.html` contains an immediate `location.replace`, a
`meta refresh` fallback, canonical URL and a visible link. `main/404.html`
covers older deep links. The old `main/sw.js` retires cached GitHub Pages
timetables and redirects navigations from already-installed legacy PWAs.
Only the **GitHub Pages copy** is replaced: **neither production VPS HTML nor
the 15-minute updater is sourced from `main/index.html`**. The canonical
generator is `build_horarios.py`; do **not** regenerate and commit
`main/index.html`, as that would restore stale GitHub Pages timetables.
The `manifest.json` in the repo remains an historical path-scoped asset,
not the root-scoped production manifest.

## How the live timetable works

Six directions connect **El Puerto de Santa María, Cádiz and Jerez**.
Filters show bus, train and catamaran; weekday tabs distinguish
Mon–Thu, Friday, Saturday, and Sunday/holidays.

- **Bus**: planned service and line notices from CMTBC
  (`siu.cmtbc.es`). If the source fails, cached bus/boat times are
  labelled *unverified*, not silently presented as fresh.
- **Rail C-1 / Media Distancia**: *date-valid* official Renfe static
  GTFS schedules, with exact-trip GTFS Realtime adjustments, station and
  trip ID checks. Realtime cancellations are red; time changes and
  uncertain delays are explained in the affected row. A train not flagged
  is a **scheduled** train, not proof it will run.
- **Catamaran B-042**: CMTBC planned departures combined with the
  official live maritime status
  `https://cmtbc.es/api/v2/web/estadomaritimo`. Exact, confirmed
  cancelled departures are red. Ambiguous notices, stale/unavailable
  sources and disruptions without uniquely identified departures
  remain yellow, never invented cancellations.
- **Verified broad incidents** (e.g. the 29 Oct 2026 SEMAF strike):
  manually sourced, dated `service_alerts.json` warnings are applied
  only to relevant trains and service dates. The notice does **not**
  automatically cancel individual departures; Renfe's explicit realtime
  cancellations take precedence. Expired advisories disappear by date.
- **Colors**: red = confirmed cancellation; yellow = change, warning
  or needs verification; unmarked = scheduled with no detected change
  (**not** confirmation). Tap a marked departure for details and source.
- **Telegram**: detected changes and certain source problems trigger
  deduplicated alerts using `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHAT_ID` and optional `TELEGRAM_TOPIC_ID` from the VPS
  environment file. No secrets belong in Git.

## Current hosting and update loop

- **VPS**: `vps-cd9917e0`, public IP `152.228.233.184`.
- **Git source checkout**: `/home/ubuntu/Sites/transport`, on `main`.
- **Original public webroot**: `/srv/www/transport`.
- **Root-scoped primary PWA HTML/assets**:
  `/srv/www/transport-pwa-root`.
- **Shared live data**: `/srv/www/transport/transport_data.json`;
  primary hostname serves it under `/transport_data.json` using an
  Nginx alias. Both public URLs show the same refreshed data.
- **Nginx vhost**:
  `/etc/nginx/sites-available/transport.peluche-ebanache.com`
  (enabled by symlink). The primary hostname has a **dedicated**
  Let's Encrypt certificate under
  `/etc/letsencrypt/live/transport.peluche-ebanache.com/`.
  Certbot renews it and reloads Nginx; `/.well-known/acme-challenge/`
  stays reachable on HTTP for renewal.
- **Recurring refresh**: `transport-update.timer` starts
  `transport-update.service` approximately **every 15 minutes**.
  It runs `deploy/refresh-vps-data.sh`, which calls
  `build_horarios.py --data-only` then **atomically replaces only**
  the public JSON. It does **not** commit/push to GitHub, publish
  GitHub Pages, rebuild AVÍO or restart Docker.
- The browser fetches the latest JSON on opening or returning to the
  foreground and periodically while visible (approximately every minute).
  The app's offline cache may contain an earlier timetable; the UI
  warns when offline. Root and path PWA caches are separate.

**Source safety before any changes:** verify host, directory and
`git status`; do not overwrite local work, reset, pull or rebuild
unexpected containers. The AVÍO Astro website is a different project at
`/srv/www/avio-site`. The transport Telegram system is not in the
AVÍO site repository. Routine diagnostic commands:

```bash
hostname
cd /home/ubuntu/Sites/transport
pwd
git status --short
systemctl status transport-update.timer --no-pager
journalctl -u transport-update.service -n 30 --no-pager
curl -fsSI https://transport.peluche-ebanache.com/
curl -fsSI https://transport.peluche-ebanache.com/transport_data.json
```

To modify the primary PWA shell, use the subdomain builder under
`deploy/subdomain/build_root.py` from the tested feature branch;
to modify service/data logic, change the corresponding source modules
and deploy only after validation. The subdomain initial staging and
TLS issue scripts are **not** routine periodic update commands.

## Route and stop rules

- El Puerto: buses prefer Plaza de Toros if the route serves it;
  otherwise show the actual stop. Railway stop: Estación FC.
- Cádiz: train stop at Plaza de Sevilla–Estación de Cádiz displays
  as Estación de Cádiz.
- Jerez: buses usually show Estación de Jerez, except M-352 from
  El Puerto, displayed at Plaza del Caballo with its **estimated**
  time derived from the La Granja offset.
- Unknown timetable day codes generate diagnostics; never fabricate
  an official operating calendar or unverified train departure.

## Historical deployment and migration notes

The following entries document older GitHub Pages deployments, the
28–29 October migration, fixes and recovery steps. **Do not follow
legacy instructions to push generated `index.html` or refresh data
by committing into GitHub Pages.** The authoritative current operation
is described above.

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
the Renfe `tripId` joins the exact GTFS service date, direction and official
train timetable row (not the older CMTBC train table). The original times remain in `salida` / `llegada`;
the new times are in `salida_actual` / `llegada_actual`.
Unmatched trip IDs and newly added trains without
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


## Move to peluche-ebanache.com/transport/ (prepared 2026-10-28)

**Goal:** serve static app shell from Nginx and refresh only
`/transport/transport_data.json` every 15 minutes. No recurring Git commits,
no Astro/Docker rebuild and no modification of the AVÍO app.

- Source checkout: `/home/ubuntu/Sites/transport`.
- Dedicated public webroot: `/srv/www/transport`; **no source files or secrets**.
- The existing service/timer remain `transport-update.service` /
  `transport-update.timer`; a new **ExecStart** override replaces the
  Git-pushing publisher with `deploy/refresh-vps-data.sh`.
- `build_horarios.py --data-only` writes JSON atomically without generating HTML.
- The PWA loads fresh JSON on opening, returning to the foreground, and every
  minute while visible. The timer still generates JSON every 15 minutes.
- Offline fallback uses the last cached JSON; when absent, it can still show
  the schedule embedded in the static HTML shell.

**Do not switch the production service before verifying Nginx.** The safe
deployment uses an isolated temporary Git worktree, leaving the currently
running `main` checkout untouched until activation.

### Phase 1 — stage files and test HTTPS (no timer or AVÍO changes)

On VPS `vps-cd9917e0`:

```bash
cd /home/ubuntu/Sites/transport
hostname
pwd
git status --short
git fetch origin
git worktree add --detach /home/ubuntu/Sites/transport-vps-prep \
  origin/feature/standalone-vps-transport-20261028
cd /home/ubuntu/Sites/transport-vps-prep
bash deploy/stage-vps-site.sh
sudo python3 deploy/enable-nginx-transport.py
curl -I https://peluche-ebanache.com/transport/
curl -I https://peluche-ebanache.com/transport/transport_data.json
curl -fsS https://peluche-ebanache.com/transport/transport_data.json \
  | python3 -c 'import sys,json; p=json.load(sys.stdin); print("routes:",len(p["data"]),"checked:",p["meta"]["checked_at"])'
```

Nginx installer is *fail-closed*: it requires the existing
`/etc/nginx/sites-enabled/peluche-ebanache.com` HTTPS server block, rejects
an existing `/transport` location, backs up config, verifies `nginx -t`,
then reloads. Failed tests revert the config. The existing
`location /` for AVÍO must be preserved.

### Phase 2 — switch the 15-minute timer to JSON-only

Only after Phase 1 succeeds:

```bash
cd /home/ubuntu/Sites/transport-vps-prep
bash deploy/activate-vps-refresh.sh
cat /home/ubuntu/Sites/transport/output/service_change_report.json
systemctl list-timers --all transport-update.timer --no-pager
journalctl -u transport-update.service -n 30 --no-pager
```

Activation first stops the old timer and waits for any running update to end;
checks clean Git state, merges the feature branch with the current `main`,
runs tests, installs a unit drop-in and starts the JSON-only updater. It
leaves the old GitHub Pages URL as a non-updating backup; **the new live URL**
is `https://peluche-ebanache.com/transport/`.

### Verification

A normal refresh should show a successful service and a changed
`/srv/www/transport/transport_data.json` modification time. Git `HEAD`
must **not** move every 15 minutes. The JSON report's `events: []` means
*no matched changes*, not proof that there were no disruptions. Confirm
matching against a real Renfe update before trusting the green status
completely.

## Renfe one-stop realtime join (2026-10-28)

Previous logic required both station updates in a single realtime entity. Live
Renfe feeds predominantly provide only one stop per train; this produced 0
matches even though static `trip_id` matches exist (C-1: 247/317; MD: 271/283
in the diagnostic snapshot). The new `renfe_static_gtfs.py` downloads Renfe
GTFS once daily and caches a compact index of trains that serve Jerez,
El Puerto or Cádiz in `output/gtfs_cache/` (ignored by Git).

- Identify the train by exact `tripId`, active service calendar and today,
  direction (ordered GTFS stops) and the exact generated Renfe timetable row.
- Only modify an endpoint time when that specific **arrival or departure**
  is explicitly provided. Do **not** extrapolate one stop to another.
- If a station inside the segment reports a delay but the endpoint timing is
  unverified, show a yellow warning instead of fabricating a green time.
- Previous-day MD services (date in `tripId`), stale feeds, implausibly large
  time differences, and unknown calendar services cannot override the schedule.
- A matching, date-valid cancellation may mark a trip red, including when the
  GTFS-RT cancellation does not provide individual station updates.
- Daily static GTFS failures are reported. A prior compact index may be used
  for up to 48 hours, with a diagnostic warning; otherwise no updates apply.
- Diagnostics now include `gtfs_ids`, `today_ids`, `matched_trips`,
  `changes` and `advisories` per Renfe feed.

Validate: `python3 -m unittest discover -s tests -v`. A normal no-change
report means **no matched active service changes**, not guaranteed punctuality.

## Official Renfe train timetables (2026-10-28 correction)

CMTBC train tables differed from Renfe static GTFS by 20–30 minutes on
28 October 2026. Real-time joins to these older clock times therefore matched
zero services. `renfe_schedule.py` now replaces only the CMTBC train rows with
Renfe static GTFS dated departures, retaining CMTBC bus and boat rows.

The existing four weekday buttons show the **nearest corresponding dates**
from the official Renfe calendar: Mon–Thu, Friday, Saturday, Sunday. The
UI displays the selected train service date once above the table, not in every row. This does **not** claim that every future weekday has
identical service; a fully date-based picker would be needed for arbitrary
future days or holiday exceptions.

GTFS-RT updates match exact `tripId` and `fecha_servicio`. They do not
guess closest time in the CMTBC table. Only explicitly updated departure and
arrival times overwrite the displayed times; the row turns **yellow** for a
change or an unresolved advisory. Confirmed cancelled trips turn **red**.

If a Renfe static feed cannot be loaded, the former CMTBC train rows stay
visible **yellow as unverified**; they must not be silently treated as official
Renfe times. JSON updates still do not create Git commits.

Diagnostics for each source are included under `meta.renfe_schedule` and the
service-change report. Tests: `python3 -m unittest discover -s tests -v`.

### Recovery when CMTBC times out during first Renfe migration

The first migration runs `git merge --squash` before requesting CMTBC. A transient
`siu.cmtbc.es` read timeout can stop the script **with the intended changes
staged but not committed**. Do **not** repeat `upgrade-renfe-gtfs.sh`, perform
`git reset --hard`, or run a second squash on top of those staged files.

The recovery entrypoint is `deploy/recover-renfe-gtfs-timeout.sh`. It first
verifies host, branch and that the Git index has exactly the tree of the
previously fetched feature snapshot (`37d6d776`). Any unrelated changes cause
it to stop rather than overwrite. It stops the refresh timer, waits for an
in-flight service, applies only the reviewed delta, runs tests and generation,
checks both Renfe schedule feeds, creates a single code commit, publishes the
HTML/JSON atomically and restarts the timer. The original public site stays
unchanged if generation fails.

CMTBC network fetches now retry once. If an individual route still cannot be
retrieved, the last valid public/local JSON is used for **bus/boat only** with
a visible unverified-source warning and a Telegram diagnostic. Official Renfe
train data is never restored from stale CMTBC clocks. If no safe cached
bus/boat route exists, generation fails without publishing a partial timetable.

## Compact mobile timetable status (2026-10-28)

A colored whole row replaces large per-trip paragraphs on the main screen:

- **Red**: verified cancellation (Renfe GTFS-RT); the scheduled time remains
  visible because the row is still listed.
- **Yellow**: reported change, partial/uncertain update, or unverified upstream
  data (e.g. a temporary CMTBC timeout). An explicitly revised departure or
  arrival is shown as the primary time, without duplicating the old time.
- **White**: ordinary scheduled trip; white does **not** guarantee punctuality.

A short two-color legend replaces the large warning banner. Users may tap or
keyboard-activate a marked row to reveal the full official message and source
link. Normal rows remain compact. The train date appears **once** above the
table (because weekday tabs show a representative upcoming date). The former
per-train `Renfe · DD/MM/YYYY` labels have been removed.

The destination cell always uses `parada_llegada` rather than a lowercase
city identifier.

Apply this UI-only change on the transport VPS with
`deploy/apply-compact-ui.sh`. This script checks host, clean Git status,
existing site and in-flight timer, then tests and creates a new HTML shell
using the **currently published JSON**, without contacting CTAN/Renfe or
changing systemd/Nginx/Docker. The JSON-only 15-minute update continues.

## Header and PWA install control (2026-10-28)

The compact mobile title is centered over the whole transport application
width, with a short location subtitle `El Puerto · Cádiz · Jerez`.
The Renfe service-date reference remains one compact line under the filters.
The red/yellow service legend now uses a restrained single-row layout where
space permits; tapping highlighted rows still reveals the source.

**Install as an app:** this site already has a scoped
`/transport/manifest.json`, a network-first `sw.js`, the three application
icons, HTTPS, and `display: standalone`. No new app store, APK, domain, or
dedicated backend is required. A small `Instalar app` control beside the
subtitle:

- On supporting Chromium browsers, stores the `beforeinstallprompt`
  event and opens the **native browser install prompt** from the user click.
- If that browser event does not fire, opens a small manual instruction for
  Android Chrome (`⋮ → Instalar aplicación` or
  `Añadir a pantalla de inicio`) or Safari on iOS (Share → Home Screen).
- Hides the control in standalone mode and on the `appinstalled` event.
- Does **not** promise an installation when the browser declines, and does not
  interfere with direct browser-menu installation or force a recurring pop-up.

To publish only this HTML change from the main checkout on the existing
transport VPS, use `deploy/apply-header-pwa.sh`. This script checks Git,
waits for the updater, runs offline tests and reconstructs only
`/srv/www/transport/index.html` from the currently public JSON. It does not
refresh upstream data, change service worker assets, modify Docker/AVÍO, or
create periodic data commits. JSON refreshes remain every 15 minutes.

After publishing: open `https://peluche-ebanache.com/transport/` in Chrome
on Android, tap `Instalar app`, confirm browser installation, launch the home
screen icon, verify the absence of the browser address bar and that reopening
the app refreshes JSON. If the browser cannot provide an install prompt, the
manual menu instructions will be shown instead. Browser installations may
show an add-to-home-screen shortcut rather than a standalone install depending
on the platform/browser.

## Android Chrome PWA installation — RGB icon compatibility test

On 2026-10-28, Chrome Android showed a disabled Install entry for the
`/transport/` app while Bottle Butler and unrelated PWAs installed on the
same device. The live site passed Chromium desktop/DevTools installability
(`Page.getInstallabilityErrors: []`) and had a controlling service worker.

A public comparison found:

- Transport launcher PNGs were **indexed palette** PNG (color type 3).
- Bottle Butler's installable icons were **truecolor RGB** PNG (color type 2),
  with a dedicated `maskable` asset.
- Transport is served in `/transport/`; Bottle Butler starts from its
  own domain root. Chromium issue
  `https://issues.chromium.org/issues/570202962` documents the **same
  disabled Android install sheet**, including path and icon qualification
  problems. However, this does not prove which condition affects this phone.

The conservative test in `fix/android-transport-pwa-install-20261028`
keeps the same origin/scope and site. It adds visually equivalent
`icon-192-rgb.png`, `icon-512-rgb.png`, and a blue, safe-zone
`icon-512-maskable.png`; uses a new manifest resource query `?v=2`
and service worker cache `transport-bahia-v4`. Source conversion is
reproducible with `python3 scripts/convert_pwa_icons.py` (Pillow required).
The binary icons are **committed**; deployment does not need Pillow.

Deploy only the PWA assets using `deploy/apply-android-pwa-icons.sh`, which
runs offline tests, prepares HTML from current public JSON, and copies
assets atomically without refetching schedules or changing the 15-minute
timer, Nginx, Docker or AVÍO.

**Validation:** Android Chrome must now offer the *enabled* `Instalar`
option in `⋮ → Instalar y crear acceso directo` and launch a separate
standalone app, not merely a Chrome shortcut. If it remains disabled,
this experiment falsifies the icon-format hypothesis; the next reasonable
diagnostic is Android Chrome version and a root-scoped subdomain staging
site, **not** resetting production or claiming success based on desktop CI.

## Recovery of interrupted PWA and maritime upgrades (29 October 2026)

The Android icon-only deployment failed **before changing main** when its
isolated source worktree did not contain `output/`; a script attempted to
write `output/pwa-install-index.html` without creating the directory.
The separate maritime status upgrade failed because the official CMTBC
`/api/v2/web/estadomaritimo` JSON response started with a UTF-8 BOM,
which `response.json()` rejected in the VPS environment.

Use the combined branch `fix/transport-recovery-20261029` and its
`deploy/apply-transport-recovery.sh` instead of repeating either older
deployment. This version:

- creates a **new isolated worktree name on every retry**, leaving both
  older failed staging trees untouched;
- runs offline unit regressions for the BOM response and RGB/maskable icons,
  and validates all shell scripts;
- creates the missing `output/` directory before rendering the HTML shell
  from the **already published JSON**, with no upstream timetable downloads
  or Telegram notifications in the staging step;
- verifies live maritime API parsing without making a timetable mutation;
- only then fast-forwards the clean production checkout and publishes
  PWA assets and index HTML atomically;
- keeps the public timetable JSON unchanged until the existing
  `transport-update.service` refreshes it, and preserves the 15-minute timer;
- never touches Nginx, the AVÍO Docker container or Git history via reset.

The maritime decoder now uses
`json.loads(response.content.decode("utf-8-sig"))`; invalid/unavailable
official data remains a yellow warning rather than an invented cancellation.
After deployment, inspect `output/service_change_report.json` for
`sources.MARITIME_B042` and the public JSON `meta.maritime`. The
`Telegram is not configured in this environment` messages from the earlier
staged generator were expected because staging lacked the systemd environment
file; they did not establish a failure of the live bot.

The RGB icon test addresses a plausible Android WebAPK compatibility issue
but does not prove Chrome will install the PWA. If Android still disables
`Instalar`, the next step is an isolated root-scoped subdomain test.

## 29 October 2026 Renfe drivers' strike: official, date-scoped notice

Renfe officially announced a 24-hour SEMAF drivers' strike on 29 October
2026, with minimum services of 75% Cercanías at peak times, 50% off-peak,
and a mean 65% of Media Distancia trains. Source:
https://grupo.renfe.com/es/es/sala-de-prensa/noticias/2026/10/establecidos-servicios-minimos-huelga-semaf-29-octubre
(published 2026-10-26).

**The legal minimum-service percentages are not individual cancellation
lists.** A normal trip in static Renfe GTFS cannot automatically be assumed
to run. `service_alerts.json` records the event as independently verified.
`source_alerts.py` applies a yellow advisory to only the matching
`fecha_servicio` C-1/MD trips on 2026-10-29; it never marks them red solely
because of the strike, and preserves exact GTFS-RT cancellations and revised
times. Only one deduplicated Telegram notice is sent for the global incident,
and a concise source-linked headline appears above the train timetable.

The alert expires after the date. Bus and ferry rows are **not** marked as
strike-affected, as this specific action concerns Renfe drivers.

One-time publication uses `deploy/publish-renfe-strike.sh`. It validates
the existing public JSON date, then applies warnings and builds HTML from
that already published JSON; the CMTBC/Renfe network does not have to respond.
It refuses to republish stale day data, checks host/clean Git, preserves
systemd updater/timer, runs tests in a separate worktree and publishes
HTML/JSON atomically. The next 15-minute refresh regenerates the same
sourced warning and sends the Telegram notice (if configured).

## Android adaptive icon enlargement (29 October 2026)

The Android launcher was using the dedicated 512 px maskable icon with a
smaller route pictogram than the existing `icon-512-rgb.png`. The larger
existing artwork keeps its blue background to the edge of the canvas and
retains the entire route pictogram within the Android maskable safe circle.
No brand shapes, colors or other assets are redrawn.

One-time publishing, **primary root-scoped PWA only**:

```bash
cd /home/ubuntu/Sites/transport
git fetch origin fix/transport-maskable-fill-20261029
git show FETCH_HEAD:deploy/publish-larger-maskable.py | python3
```

The script checks VPS hostname, source path, clean `main` checkout, root
manifest and expected service-worker version before changing anything.
It atomically replaces `/srv/www/transport-pwa-root/icon-512-maskable.png`
with the already-committed larger truecolor PNG, increments the root
service-worker cache from v1 to v2 and root HTML manifest query from v2 to
v3. It does not rebuild HTML/data, touch Certbot, AVÍO or Git and rolls
back static files if an update fails.

The regular `/transport/` backup path and its independent PWA remain
unchanged. On Android, a previously installed WebAPK may need to be
uninstalled and installed again to display the new launcher icon. Do not
run this script on every 15-minute update. A future full root-PWA rebuild
must preserve the new image sizing/cache version.

## Passenger-facing Renfe messages (29 Oct 2026)

Raw `https://gtfsrt.renfe.com/trip_updates*.json` URLs are for ingestion
and diagnostics only. They **must not** appear in Telegram alerts or as
downloadable links on the timetable. The source feed URLs are retained in
internal records for provenance.

When realtime identifies an exact train's changed arrival/departure,
`transport_updates._passenger_rail_times` displays actual clock times and
only the corresponding minute difference, e.g.:

`Renfe · Salida 11:20 · Llegada 11:30 (+1 min)`

The arrival was previously 11:29; the 11:20 departure is unchanged.
Origin-only or destination-only updates never infer the other station's
revised time. Cancelled trains continue to be marked red, uncertain
delays yellow, and independently sourced strike notices are preserved.

For **C-1**, Telegram and timetable point to the official public
Renfe Cercanías realtime viewer
`https://tiempo-real.renfe.com/?lang=es`, rather than the machine feed.
For **MD**, the notification identifies the official Renfe data source
without linking to a raw JSON file or suggesting a viewer that is not
known to cover those trips. The Telegram bot sends all text notifications
with `link_preview_options.is_disabled=true`, preventing unwanted file
attachment-style preview cards. Other official, genuinely readable
public news/source links are preserved.

**Deployment:** `deploy/publish-passenger-alerts.sh` validates the
source checkout and tests in a separate worktree, then fast-forwards
main and patches only the matching source-link block in
`/srv/www/transport/index.html` and
`/srv/www/transport-pwa-root/index.html`, without regenerating
full HTML or touching the published JSON. The timer is stopped only
for the brief source update, restored and then triggered asynchronously.
Do not deploy by pushing generated HTML to GitHub Pages.

## Renfe Telegram anti-spam rules (30 October 2026)

The **website keeps all verified changes**, even one-minute adjustments,
and the normal cancelled/warning highlights. Only Telegram messages are
filtered more strictly by `rail_notifications.py`:

- Departure **later by 1–5 minutes**: no message; **6+ minutes**: message.
- Departure **earlier by any amount**, including 1 minute: message, because
  this may cause the passenger to miss the train.
- Arrival earlier or later by **up to 5 minutes**, inclusive: no message;
  **6+ minutes** in either direction: message.
- A warning about an intermediate stop without a verified revised time
  goes to Telegram only for **10+ minutes of reported delay**. The original
  yellow warning stays in the timetable.
- A confirmed cancellation or a skipped station is always eligible for
  an immediate warning while the service is relevant; services completed
  more than 15 minutes ago do not generate belated notices.

A Renfe `tripId` identifies a **physical train**. Any references to
the same train in Cádiz→Jerez and El Puerto→Jerez are merged: relevant
departure/arrival changes are listed by station, not repeated across
separate city-pair messages. Several different newly affected trains found
in one 15-minute refresh are reported **in one Telegram message**, within
the Telegram length limit.

Notification state is preserved under
`output/service_change_notifications.json`. An already-reported train
is not re-announced for every one-minute fluctuation of the feed:
an additional alert requires at least **10 minutes more serious timing
deviation** than the last reported value, a newly earlier departure
or a new cancellation/skipped stop. Subsequent earlier-departure
changes have a 5-minute worsening threshold.
Previously sent per-route train alerts are recognized on migration to
the per-trip key to avoid a one-time alert flood. Failed sends are not
recorded as successful. Bus, ferry and official global-incident alerts
keep their existing deduplication rules.

Deploy with `deploy/publish-rail-alerts-antispam.sh` after automated tests
pass. It verifies clean `main` on `vps-cd9917e0`, tests from an isolated
worktree, stops the 15-minute scheduler during source fast-forward,
restores the timer and starts one asynchronous data refresh.
Do **not** delete the notification-state JSON or reinstall the bot.
No Git commits are generated by routine timetable updates.

## Rejecting impossible Renfe realtime times (30 October 2026)

An MD prediction once said **Cádiz 17:24 → El Puerto 16:38**
(70 minutes before its planned arrival). It was not evidence that the train
arrived before departure; it was a **data inconsistency**, and the old
display/Telegram alert incorrectly treated it as confirmed.

`transport_updates._coherent_segment_times` now compares the GTFS
scheduled journey duration with exact-station departure and arrival
updates. It handles trips crossing midnight via signed minute differences,
but rejects any predicted duration **less than or equal to zero** or
at least 24 hours. Missing/malformed explicit station predictions are
also treated conservatively. Neither revised endpoint is published if
the pair is inconsistent; both planned times are shown with a **yellow
warning** (not a verified arrival time), and `invalid_times` increments
in the diagnostic source counters. Cancellation status stays higher priority
and no revised times are published for cancelled services.

The Telegram alert for a newly discovered inconsistency is once per
physical train: `Renfe · Horarios incoherentes; comprobar este tren`,
without the impossible hour. Existing anti-spam deduplication applies.
If the data is corrected later, a significant, credible time change
can be announced normally.

The machine-readable Renfe MD URL remains internal to the parser.
Telegram **does not append** the unsupported
`MD: datos oficiales de Renfe` footer; the timetable also omits
its unclickable source attribution. The public C-1 passenger link remains.

To publish after tests: use the guarded
`deploy/publish-passenger-alerts.sh` already in `main`. It validates both
installed HTML shells before patching, retains the shared public JSON,
fast-forwards the source checkout without discarding local changes,
restores the 15-minute timer, and triggers the normal data refresh.

## RadarDeTrenes station-board observer — not ADIF confirmation (30 Oct 2026)

**Observed live on all three endpoints**:
`https://radardetrenes.com/api/v1/stations/51405/board-renfe` (Cádiz),
`/51400/board-renfe` (El Puerto) and `/51300/board-renfe` (Jerez).
They return `departures`, `arrivals`, `trainCode`, `stationCode`,
`plannedTime` (epoch milliseconds), `delayMinutes`, `updatedAt`,
and `source: "renfe_official"`. Although RadarDeTrenes also aggregates
some ADIF data, **these specific station feeds identify Renfe as their
origin**. They are a secondary parsing/transport chain, **not**
independent evidence from ADIF. Do not infer ADIF confirmation from their
results. API documentation: https://radardetrenes.com/docs

`radar_shadow.py` polls those three station boards once per live
15-minute timetable refresh, requests at most three responses, uses a
6-second per-source timeout and fails open for the existing site.
It only compares **today's Media Distancia** trains with a strict composite
key of station code + exact five-digit train number parsed from the
date-scoped Renfe static GTFS ID + scheduled clock time + departure/arrival
kind. It checks source provenance and freshness (no older than 10 min)
and records delay conflicts of at least five minutes.

Diagnostics live **only** in
`output/service_change_report.json → sources.RADAR` (status,
healthy/requested, matched, conflicts, sample train codes and delays).
A train missing from a board's rolling window is not marked cancelled.
`transport_data.json`, passenger times, yellow/red statuses, Telegram
deduplication and alerts remain entirely controlled by the existing
Renfe GTFS realtime and independently verified notices.
Never auto-promote the third-party board to a cancellation/green
confirmation or "ADIF verified" state.

The API is free and no key is required; its conditions request attribution
to RadarDeTrenes, Renfe and ADIF for redistributed data. This stage
redistributes no board data. If a future public feature uses it, add
visible attribution. Consider requesting authorized ADIF Elcano feed
access separately; its access-key-based interface is not an open public
API. Only use independent-ADIF logic after provenance and train matching
have been validated, especially for MD.

One-time source update: `deploy/publish-radar-shadow.sh`. This guarded
script verifies VPS host/clean main, runs offline tests, fast-forwards
source without discarding local changes, restores the existing 15-minute
systemd timer and starts one refresh. No Nginx/AVÍO/rebuild/periodic Git
commits or changes to user-facing messages.
