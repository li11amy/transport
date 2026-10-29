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

## Root-scoped PWA on separate transport hostname (29 October 2026)

Android Chrome did not permit WebAPK installation from the path-scoped
`https://peluche-ebanache.com/transport/` app, even after RGB launcher
icons were updated and Chromium DevTools showed no installability errors.
A separately hosted root-scoped PWA is prepared at
`https://transport.peluche-ebanache.com/`; the old page stays online as
a fallback. This is a compatibility experiment, not yet verified on Android.

The standalone root PWA has:
- `manifest.json`: `id=/`, `start_url=/`, `scope=/`, RGB and
  maskable icons at the new origin root;
- `sw.js`: scope `/` and independent
  `transport-bahia-root-v1` offline cache;
- `index.html`: identical visual and service-alert logic to
  the path-scoped page, but root-relative service-worker and assets;
- `/transport_data.json`: **Nginx alias** to the existing
  `/srv/www/transport/transport_data.json` from the original 15-minute
  updater; no duplicated parser, scheduler, DB or Git commits.

All independent static assets reside under
`/srv/www/transport-pwa-root`. This is **not** the Astro AVÍO directory
`/srv/www/avio-site`. Original `/srv/www/transport` is untouched.

### DNS and TLS prerequisites

Create a **proxied CNAME** in Cloudflare DNS for the zone
`peluche-ebanache.com`:

- Type `CNAME`
- Name `transport`
- Target `peluche-ebanache.com`
- Proxy `Proxied`

This is a separate hostname pointed at the same VPS. It must be live in
DNS before enabling the Nginx vhost.

The safe installer `deploy/subdomain/enable_https.py` also checks that
the currently configured TLS certificate of
`/etc/nginx/sites-available/peluche-ebanache.com` covers
`transport.peluche-ebanache.com`. It **does not** assume that an ordinary
single-domain certificate is a wildcard, and will refuse to change Nginx
if the certificate does not cover the subdomain. In that case a new valid
certificate must be obtained and the vhost installer updated accordingly.
The existing AVÍO Nginx configuration is never overwritten.

### Staging/activation

On the transport VPS, with a clean main checkout:

```bash
cd /home/ubuntu/Sites/transport
git fetch origin feature/transport-root-subdomain-20261029
git show FETCH_HEAD:deploy/subdomain/stage-and-enable.sh | bash
```

The script checks host, working directory and Git status, creates a
fresh isolated worktree, runs offline tests, copies only static assets into
the independent webroot, then attempts guarded HTTPS activation.
If DNS or matching TLS is missing, it prints the reason and **does not**
modify Nginx or Git main. The old /transport/ app stays available.

After HTTPS activation, verify
`https://transport.peluche-ebanache.com/` and
`https://transport.peluche-ebanache.com/transport_data.json`.
Then test Chrome Android `Instalar`: only an independently launched
standalone home-screen application counts as success.

### Dedicated Let’s Encrypt certificate after initial staging (29 Oct 2026)

Initial staging **succeeded**, but TLS activation refused the old
`/etc/letsencrypt/live/peluche-ebanache.com/fullchain.pem` because it
does **not** cover `transport.peluche-ebanache.com`. The proxied A record
`transport → 152.228.233.184` is correct; there is no need to replace
it with a CNAME.

The follow-up bootstrap is `deploy/subdomain/issue-and-enable-https.sh`.
Do not rerun the original `stage-and-enable.sh` or rebuild the PWA.

It checks the VPS host, working folder, clean Git and prepared root assets,
then installs a **temporary and reversible** port-80 Nginx vhost for
`/.well-known/acme-challenge/` only. The script verifies the challenge
file can be fetched both directly from the local Nginx and through
Cloudflare before requesting a dedicated Let's Encrypt certificate
with Certbot's webroot plugin. Only
`/etc/letsencrypt/live/transport.peluche-ebanache.com/` is used for
the new certificate: the existing main-domain certificate is untouched.

After issuance, `enable_https.py` replaces the precisely identified
temporary vhost with an HTTP/HTTPS transport vhost, and retains
`/.well-known/acme-challenge/` on HTTP for future certificate renewals.
A deploy hook reloads Nginx when Certbot successfully renews it.
If challenge validation or Certbot fails, the temporary HTTP vhost is
removed; unrelated Nginx hosts and the existing /transport/ site remain
unchanged. Cloudflare WAF or redirect rules can block the initial HTTP-01
check; fix the challenge route rather than force an unsafe TLS fallback.

Run:

```bash
cd /home/ubuntu/Sites/transport
git fetch origin feature/transport-root-subdomain-20261029
git show FETCH_HEAD:deploy/subdomain/issue-and-enable-https.sh | bash
```

Certbot may ask for email/ACME account agreement if there is no already
registered account on the VPS. Do not paste certificate private keys into
ChatGPT. The script does not replace the main-domain certificate, does not
modify the AVÍO website and does not touch the JSON refresh timer.

After activation, validate HTTPS and Android installation, then verify
that Certbot's existing automatic renewal timer is enabled using
`systemctl list-timers --all | grep -Ei 'certbot|letsencrypt'`.
The new certificate's renewal settings retain its webroot challenge and
Nginx reload deploy hook.
