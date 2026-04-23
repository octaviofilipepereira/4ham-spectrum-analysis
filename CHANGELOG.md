<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-04-18 UTC
-->

# Changelog

## v0.14.0 - 2026-04-23 (unstable)

### Added — External Mirrors (push replication) + Public Dashboard mirror
- **New module `backend/app/external_mirrors/`** — push selected dashboard data
  (callsign + occupancy events) to one or more remote PHP/MySQL hosts over
  HTTPS, eliminating the need for inbound port-forwarding on the production
  station. Includes:
  - SQLite tables `external_mirrors` (configuration, bcrypt-hashed token) and
    `external_mirror_audit` (per-event audit log).
  - `MirrorHttpClient` with HMAC-SHA256 request signing
    (`X-4HAM-Signature`, `X-4HAM-Timestamp`, `X-4HAM-Nonce`,
    `X-4HAM-Mirror-Name`, `X-4HAM-Mirror-Version`), TLS-verify on by default,
    30 s timeout, 3 retries on 5xx/network/timeout with exponential back-off
    (no retry on 4xx).
  - Watermark-based payload builder (`payload.py`) with `MAX_BATCH_SIZE=5000`.
  - Background pusher loop (`pusher.py`, default tick = 15 s) integrated into
    the FastAPI app lifespan; auto-disables a mirror after 5 consecutive
    failures.
- **Snapshot bundler** (`backend/app/external_mirrors/snapshots.py`) — every
  push payload now embeds pre-computed JSON bodies for the read-only API
  endpoints used by the public dashboard (`version`, `scan/status`,
  `settings`, `map/ionospheric`, `map/contacts`, `analytics/academic`).
  Builders invoke the live FastAPI route functions in-process, so the JSON
  is byte-equivalent to what the home backend would serve. Builders that
  fail are silently skipped; failure of any builder never breaks the push.
  - `settings` snapshot uses a public projection (strips
    `auth/aprs/lora_aprs/asr/device_config/audio_config`).
  - `analytics/academic` snapshot caps embedded `raw_events` at 1500 rows
    to keep push payload under 8 MB shared-hosting limits; the dashboard
    only renders a sliding window so older rows are not user-visible.
- **Admin REST API** at `/api/admin/mirrors` (Basic-auth protected): list,
  create, edit, enable/disable, rotate-token, test, delete and audit-log
  endpoints. Plaintext tokens are returned ONLY at create / rotate-token
  and are never persisted in clear.
- **Admin Config UI** (inside the existing Admin Config modal): mirror table,
  add/edit form, one-time token alert, per-row enable/disable, rotate-token,
  test push and audit log viewer.
- **PHP/MySQL receiver** in `external_academic_analytics/` for shared
  hosting (PHP 7.4+, PDO_mysql only). Includes:
  - MySQL schema with `mirror_callsign_events`, `mirror_occupancy_events`,
    `mirror_endpoint_snapshots`, `mirror_push_audit`, `mirror_seen_nonces`.
  - Idempotent `INSERT IGNORE` ingest endpoint with HMAC + nonce +
    clock-skew verification, IP allowlist and audit log.
  - 7 read-only API shims under `api/` (`version`, `scan/status`,
    `settings`, `map/ionospheric`, `map/contacts`, `analytics/academic`,
    `events`) — 6 serve verbatim snapshot JSON, `events` reads live SQL
    over the mirrored event tables.
  - `index.html` = verbatim copy of `frontend/4ham_academic_analytics.html`
    + vendored Leaflet/D3/TopoJSON/XLSX assets and i18n JSON, providing a
    fully public, read-only replica of the Academic Analytics dashboard
    (max 5 min staleness, no WebSocket, no admin surface).
  - `api/.htaccess` extension-less routing; `Header` directive guarded by
    `<IfModule mod_headers.c>` for hosts without `mod_headers`.
  See `external_academic_analytics/README.md` for deployment.
- **Documentation**: new `docs/external_mirrors.md` covering architecture,
  snapshot bundle, security model, admin UI walkthrough, receiver
  deployment and the public dashboard mirror.

### Changed
- **Version bump** to v0.14.0 across backend (`APP_VERSION`).
- Receiver folder renamed from `external_academic_analytics_mirror/` to
  `external_academic_analytics/` to match the production deployment path.

---

## v0.13.3 - 2026-04-22

### Documentation
- **Documentation overhaul**: simplified user manuals (EN/PT), installation manual, README, ROADMAP (EN/PT), CHANGELOG and in-app help (`help.html`) to focus exclusively on the supported APRS pipeline (Direwolf VHF + APRS-IS).
- **Version bump** to v0.13.3 across backend (`APP_VERSION`), help badge, and Academic Analytics dashboard title.

---

## v0.13.2 - 2026-04-22

### Changed
- **APRS map UX iteration** (cumulative result of multiple frontend tweaks merged from `unstable`): refined marker colours (RF orange, APRS-IS green, QTH blue), leader-lines for stacked stations sharing identical coordinates, vertically stacked overlapping callsign labels, collision detection across a 3×3 bucket neighbourhood, and adjustable initial map zoom (final value: 11). Mode switches now clear stale markers and only reload on actual mode change. Initial APRS view persists user filters/preset and uses a wider 24h position snapshot to anchor markers.
- **Academic Analytics dashboard title** bumped to v0.13.2.

---

## v0.12.4 - 2026-04-18

### Added
- **Academic Analytics export enrichment**: the "All Events" sheet (XLSX) and CSV export now include 13 additional fields per event — DXCC entity name, continent, DXCC code, latitude, longitude, power (dBm), confidence, crest (dB), Doppler shift (Hz), source, grid locator, derived band, and normalised mode.
- **Human-readable export column headers**: all export column headers now use descriptive names with measurement units (e.g. "Frequency (Hz)", "SNR (dB)", "Power (dBm)") instead of internal snake_case identifiers.

### Documentation
- Updated README changelog, help.html, user manuals (EN/PT), and ROADMAP (EN/PT) with enriched export details.

---

## v0.12.3 - 2026-04-17

### Added
- **Preset Scheduler**: time-of-day automatic rotation of scan presets. New `preset_schedules` DB table, `PresetScheduler` background task (30 s tick), 6 new API endpoints (`GET/POST /rotation/schedules`, `PATCH/DELETE /rotation/schedules/{id}`, `POST /rotation/scheduler/start|stop`).
- **Scheduler auto-start on boot**: if enabled schedules exist in the DB, the scheduler starts automatically during app lifespan — no manual start required after server restart.
- **Scheduler rotation recovery**: if the rotation dies unexpectedly (preview mode, error, user action), the scheduler detects it within 30 s and re-applies the active preset.
- **Schedule overlap validation**: `POST /rotation/schedules` returns HTTP 409 with descriptive message when a new schedule collides with an existing enabled schedule. Handles same-day and cross-midnight windows.
- **UTC clock in scheduler UI**: live UTC clock displayed next to the Preset Scheduler title for unambiguous time reference.
- **Frontend Preset Scheduler section**: inside Rotation Presets modal — Add/Delete/Enable-Disable schedules, Start/Stop Scheduler, status badge, schedule table sorted by start time.

### Fixed
- **Schedule preset dropdown empty on modal open**: race condition where schedules loaded before presets — now presets load first (`await`).
- **Graceful scheduler shutdown**: scheduler is stopped cleanly on app exit.

---

## v0.12.2 - 2026-04-12

### Changed
- **SNR KPI split**: replaced single "Average SNR" card with two separate cards — "Avg SNR FT4/FT8/WSPR" (WSJT-X 2500 Hz BW reference) and "Avg SNR CW/SSB" (DSP real bandwidth). Prevents mixing incompatible measurement scales.
- **Backend API**: new fields `snr_avg_digital` and `snr_avg_analog` in `/api/analytics/academic` KPIs response (backward-compatible: `snr_avg` retained).
- **Removed Time Coverage KPI card** (redundant — gaps visible in Event Time Series chart).
- **Renamed** "Overall Propagation score" → "Global Propagation".

### Documentation
- **User manuals** (EN/PT): new section "Embedding the Academic Dashboard on an External Website" — covers Apache+PHP and Nginx reverse proxy setup, architecture, security, and troubleshooting.

---

## v0.12.1 - 2026-04-12

### Added
- **QTH-Centric Propagation Map — complete redesign**: DR2W-style irregular solar-shaped propagation zones per band with 3 intensity layers (Strong / Moderate / Fringe), shaped by solar elevation angle. Zone boundaries computed from real-time NOAA SWPC indices via a calibrated ionospheric model.
- **NOAA SWPC Ionospheric Space Weather sidebar**: 1/4-width panel to the right of the globe showing real-time SFI (Solar Flux Index), Kp (geomagnetic index), and foF2 (estimated F2 critical frequency). Per-band status pills: **Open** (green) / **Marginal** (amber) / **Closed** (crimson) / **Absorbed** (grey). Auto-refresh every 15 minutes.
- **Backend ionospheric model** (`/api/map/ionospheric`):
  - foF2 calibrated against ionosonde data: `foF2 = 3.5 + 0.6 × √SSN` MHz, with 45 % night floor.
  - SSN-dependent D-layer absorption: `k = (500 + 4×SSN) / f² × sin(solar_elevation)`, ±15 dB tolerance.
  - Multi-hop skip model: 2 500 km per ionospheric hop, maximum 4 hops.
  - NVIS cap: bands < 8 MHz in daylight limited to near-vertical-incidence skip when D-layer prevents long-distance propagation.
  - Band status re-evaluated after D-layer absorption: NVIS-only propagation → Marginal; full absorption → Absorbed.
- **Map layout**: 3/4-width globe (CSS span-9) + 1/4-width ionospheric sidebar (span-3).
- **Map controls**: Ctrl+Mouse Wheel zoom, drag to rotate, double-click to reset; zoom level and globe rotation persisted via `sessionStorage`.
- **Split map legend**: contacts + count (left panel), zone intensity swatches (right panel).
- **Band buttons**: vertical layout, toggle-per-band, persisted via `sessionStorage`, none selected by default; active band shown in its unique colour, inactive in white.
- **Graticule degree labels and band labels** scale proportionally with zoom level.
- **Day/night terminator**: dashed yellow line from subsolar point; dark-hemisphere overlay; antipodal calculation corrected.

### Changed
- **Map**: band buttons resized to taller, wider vertical style for usability.
- **ionoBadge legend footer**: includes Open / Marginal / Closed / Absorbed colour key and "⟳ Auto-refresh every 15 min" note.
- **Propagation zones**: opacities calibrated — weak 0.08, moderate 0.14, strong 0.22.

### Documentation
- **help.html** updated to v0.12.1 — new sections: *QTH-Centric Propagation Map* and *Ionospheric Space Weather panel*.
- **User manuals** (EN/PT) updated — new chapters on propagation map, ionospheric model, and band status interpretation.
- **README** changelog updated to v0.12.1.
- **ROADMAP** (EN/PT) updated — v0.12.1 milestone added.

---

## v0.11.1 - 2026-04-10

### Fixed
- **SQLite concurrency fix** — added `self._lock` to 5 auth/session database methods (`get_auth_config`, `save_auth_config`, `get_auth_session`, `save_auth_session`, `clear_auth_session`) that were missing thread-safety protection. Eliminated ~705 `sqlite3.InterfaceError` per day (8.3% of requests). CPU usage dropped from 243% to 37%, memory from 1.63 GB to 580 MB.
- **SSB marker flood fix** — 60 s debounce + SNR ≥ 8 dB gate on voice markers; voice marker cache preserved before debounce.
- **Phantom SSB event elimination** — BW cap at 2800 Hz across all 4 filtering points (pipeline, events, decoders, helpers).
- **Backend `band_display` update** after SSB subband clipping.
- **Focus hold coverage improvement** — `hold_ms` 15→10 s, auto formula `span÷15k`, max 16.

### Changed
- **Help panel** updated to v0.11.1.
- **Academic Analytics** version header updated.
- **Roadmap** (EN/PT) bilingual audit — 15+ inaccuracies corrected against codebase.

## v0.10.0 - 2026-04-08

### Added
- **Scan Rotation scheduler** — automated multi-band/mode cycling with configurable dwell time, loop option, and live countdown status bar. Full UI panel with slot editor and WebSocket sync.
- **Comprehensive Academic Analytics documentation** — full interpretation guide, export walkthrough, and KPI reference in help.html and user manuals (PT/EN).
- **Propagation scoring reference v1.2** — exact mathematical formulas, verification penalty, band score aggregation, and complete SNR parameters table (15 modes). Cross-referenced in README, help.html, and both user manuals.
- **OS compatibility documentation** — all docs now list exact supported distributions matching installer validation: Ubuntu 20.04+, Debian 11+, Linux Mint 20+, Raspberry Pi OS 11+.

### Fixed
- **Phantom modes in analytics charts** (two-layer fix) — occupancy events forced to match active decoder mode in events.py (prevents DSP bandwidth heuristic mis-classification as SSB during FT8/CW scans); confirmed_band_modes SQL query time-scoped to analysed period in analytics.py (prevents historical sessions from polluting current charts).
- **UTC interpretation of custom date inputs** — frontend datetime-local inputs now append 'Z' suffix, forcing UTC interpretation. Prevents off-by-one-day boundary errors for users in non-UTC timezones (e.g. Europe/Lisbon UTC+1). Fixed in both Academic Analytics and Events Search.
- **SDR device release on rotation stop/start** — proper device release and preview restore when stopping/restarting rotation scan.
- **Map per-table event limit** — prevents band starvation with dedup by callsign+band.

### Changed
- **Rotation panel UX** — disabled state styling, API URL fix, device auto-detection, page refresh persistence.
- **Scan controls layout** — reorganised buttons and renamed for clarity.
- **Help panel** updated to v0.10.0.

## v0.9.0 - 2026-04-06

### Added
- **3-formula propagation scoring** — separate scoring formulas for Digital (FT8/FT4/WSPR/FST4W/Q65), CW, and SSB modes, each with tailored SNR normalisation and weighting. Server-computed scores served via `/api/analytics/academic`.
- **Export multi-format** — Academic Analytics dashboard now exports data in CSV, XLSX (with Aggregated + All Events sheets), and JSON via a dropdown button.
- **1 h / 12 h presets** — new short-period presets in the analytics dashboard with automatic minute-level bucketing for higher time resolution.
- **Loading overlay** — visual spinner overlay when switching time periods or applying filters, preventing interaction during data fetch.
- **Callsign ITU validation** — all callsigns are now validated against a two-branch ITU amateur radio regex (letter-start and digit-start patterns), rejecting invalid strings like "5I5I".
- **Propagation scoring reference docs** — new `propagation_scoring_reference.md` (EN) and `propagation_scoring_reference_pt.md` (PT) with full formulas, constants, and implementation tables. PDF exports included.

### Fixed
- **Empty analytics on short periods** — the confirmed-modes pre-scan now queries the entire `callsign_events` table instead of just the time-filtered window, preventing blank dashboards for 1 h periods without callsign events.
- **Heuristic-only mode filtering** — occupancy events from DSP heuristic classification (SSB, WSPR, FT4, FSK/PSK, AM) are now excluded when no decoder-confirmed callsigns exist for that mode, preventing misleading "phantom" mode entries.
- **CW_TRAFFIC not in frontend CW_MODES** — added `CW_TRAFFIC` to the frontend `CW_MODES` set for correct SNR normalisation.
- **Missing SNR_PARAMS** — added `FST4W`, `Q65`, and `VOICE_DETECTION` to the frontend `SNR_PARAMS` map.
- **Verification threshold mismatch** — frontend verification threshold changed from `>50` to `>5` to match backend.
- **Stacked bar minimum height** — enforced 3 px minimum segment height in stacked bar charts.
- **CW_CANDIDATE/CW_TRAFFIC band=NULL** — events with missing band field now included in analytics.

### Changed
- **Immediate preset switching** — clicking a period preset (1 h, 12 h, 24 h, 7 d, 30 d) now loads data immediately without needing Apply Filters.
- **Preset persistence** — selected period preset is saved in `sessionStorage` across page refreshes.
- **Top Callsigns** — chart expanded to top 20 and fills card height.
- **Heatmap Pro** — larger Σ labels, hover tooltips on marginal bars, KPI renamed to "Overall Propagation score".
- **Author field** — updated to "Octávio Filipe Gonçalves | Indicativo: CT7BFV / Projecto: 4ham-spectrum-analysis" in docs.

### Documentation
- **Help panel** updated to v0.9.0.
- **Propagation scoring reference** validated against codebase — 5 discrepancies found and fixed.

## v0.8.7 - 2026-04-05

### Added
- **Desktop launcher shortcut** — on graphical systems (GNOME, Cinnamon, XFCE, KDE, MATE, LXQt), the installer offers an optional desktop shortcut. Double-click opens an interactive terminal menu with: Open Dashboard, Start / Restart / Stop Server. Launcher script: `scripts/4ham_launcher.sh`. Uninstaller removes the shortcut automatically.
- **Check for Updates button** — new button in Admin Config performs `git fetch/pull` and auto-restarts the server when updates are available.
- **Installer Whisper model choice** — choose between `tiny`, `base`, or `small` Whisper models during `./install.sh` setup, with a description of pros/cons for each.

### Fixed
- **Academic Analytics normalization** — `SSB_TRAFFIC` events now counted as `SSB` and `CW_CANDIDATE` as `CW` in all analytics charts (timeline, band distribution, heatmap, propagation).
- **RTL-SDR v4 install path** — reinstalls SoapySDR Python module inside the venv and properly blacklists the `rtl2832_sdr` kernel module.
- **RTL-SDR hotplug** — Refresh Devices button now applies the correct gain and sample rate when an RTL-SDR is detected.
- **Desktop shortcut Exec quoting** — paths with spaces are now properly quoted in the `.desktop` file.

### Changed
- **Decoder Status UI** — shows Configured / Running / Stopped for each decoder instead of just Disabled.
- **Admin Config layout** — Purge / Reset defaults / Reset total buttons moved to a second row; all Admin buttons documented in help.
- **Whisper gauge message** — clarified that the model downloads on first run, not during install.

### Documentation
- **Help panel** updated to v0.8.7 — new Desktop launcher section (§12), renumbered FAQ to §13.
- **README, install.md, installation_manual.md, CHANGELOG** — updated with desktop launcher, version bump, and new features.

## v0.8.5 - 2026-04-03

### Added
- **Academic Analytics dashboard** — new page (`/4ham_academic_analytics.html`) with aggregated charts: activity timeline, band distribution, Heatmap Pro (hour × band with cross-highlight and marginal totals), and propagation map. Auto-refreshes every 60 s with period selector (1 h–All). Backend endpoint `/api/analytics/academic`.
- **Data Analysis toolbar button** — added in the main UI toolbar (before Help), opens the analytics dashboard in a new browser tab.
- **Version endpoint** — `/api/version` returns the running application version.

### Changed
- **Environment file moved to project-local `.env`** — previously at `/etc/default/4ham-spectrum-analysis` (required sudo); now at `<project>/.env` (no sudo needed). Systemd service template, install and uninstall scripts updated.
- **html2canvas served locally** — replaced the last CDN reference (`cdnjs.cloudflare.com/html2canvas`) with a local copy in `frontend/lib/`. Zero external CDN calls.

### Documentation
- **Help panel** updated to v0.8.5 — new Academic Analytics section, Data Analysis button documented in interface tour.
- **README, install.md, installation_manual.md, ops_packaging.md, user_manual.md** — updated with `.env` migration, analytics page route, and version bump.

## v0.8.4 - 2026-04-03

### Added
- **Decoder Status modal** — now shows all active decoders (CW, SSB/ASR, PSK) with running/stopped status. The redundant Internal FT row was removed. PSK shows a static "Not available" label (decoder not yet implemented). SSB queue depth is hidden when 0 (shown only when there are pending segments).

### Fixed
- **VOICE DETECTED marker flood on mode switch** — switching modes (e.g. CW → SSB) was flooding the waterfall with historical "VOICE DETECTED" markers. Root cause: markers created from historical events used `Date.now()` instead of the original event timestamp, making old events appear fresh and survive their full TTL. Fixed by using `seenAtMs` (original event time) in all three marker creation paths in `waterfall.js`.
- **Backend voice marker cache not cleared on scan stop** — `state.voice_marker_cache` persisted across mode switches, causing stale SSB_VOICE markers to continue appearing in spectrum frames after switching to a different mode. Cache is now cleared in `scan_stop()`.
- **Events card showing wrong mode after mode switch** — Events panel continued showing the previous mode's events until the first decode in the new mode. Fixed by calling `fetchEvents()` and `fetchTotal()` immediately after the mode switch, and syncing `eventsSearchModeInput` with the new mode.
- **Frontend marker cache not cleared on mode switch** — `decodedMarkerCache` now cleared when switching modes, preventing markers from previous mode polluting the new mode's waterfall.
- **SSB Traffic event spam** — debounce interval increased from 8 s to 30 s per 2 kHz bucket; added SNR floor gate (rejects signals below `snr_threshold_db`, default 8 dB); SSB_VOICE markers now only injected when ASR confirms actual voice (not on occupancy-only detections).
- **libuhd SIGSEGV crash** — `SoapySDR.Device.enumerate()` now runs in a subprocess so a native crash in `libuhd.so` kills only the child process, not the main server.
- **Waterfall tooltip "last" field empty** — added `|| marker?.seen_at` fallback for `embeddedSeenAtMs` in tooltip rendering.

### Documentation
- **SSB Max Holds parameter** — documented `ssb_max_holds` in `help.html` and `user_manual.md`; corrected SSB marker TTL and description in the Help panel.
- **Operational scripts** — `uninstall.sh` and `server_control.sh` documented in `docs/install.md` and `docs/installation_manual.md`.
- **Help panel updated to v0.8.4** — SSB flood protection, marker behaviour, FT decoder details, and FAQ entries added.

## v0.8.3 - 2026-04-02

### Added
- **VOICE DETECTED waterfall markers** — SSB Voice Signature events now produce real-time markers on the waterfall overlay, labeled "VOICE DETECTED" with a distinctive black-and-gold style. Markers are injected from both the occupancy detector and the ASR/Whisper pipeline into a shared `voice_marker_cache`.
- **Mode-filtered event fetch** — switching modes (SSB → CW → SSB) no longer loses events; `fetchEvents()` now sends the active mode filter to the API so the 200-event limit returns only relevant results.

### Changed
- **VOICE DETECTED marker TTL** — increased from 15 s to 45 s (backend and frontend) to survive natural pauses between SSB "overs" without flickering.
- **Marker thresholds** — `MARKER_MIN_SNR_DB` lowered from 10 → 8 dB; `MARKER_MAX_AGE_S` raised from 10 → 30 s for better SSB sensitivity on typical HF noise floors.

### Fixed
- **ASR startup crash** — ASR configuration is now restored from the database at application startup, preventing a crash when the scan resumes with ASR enabled.

## v0.8.2 - 2026-03-25

### Added
- **SSB ASR pipeline activation** — `parse_ssb_asr_text()` wired into the live SSB event pipeline. Whisper transcripts are now parsed for callsigns (direct and NATO phonetic) in real time.
- **SSB event labels** — events now show **Voice Confirmed** (voice only), **Voice Transcript** (has transcript, no callsign), or the **resolved callsign** — replaces the old generic "NO CALLSIGN DETECTED".
- **TXT button & tooltip** — every SSB event shows a TXT button with decoded text (transcript or spectral proof). For SSB, raw transcript is prioritised over spectral summary. Tooltip uses a `position: fixed` overlay that works inside modals and overflow-clipped panels (z-index 1090).

## v0.8.1 - 2026-03-24

### Fixed
- **SDR enumerate segfault** — `SoapySDR.Device.enumerate()` was called on every HTTP health/status request, triggering native USB code (`libuhd.so`) that segfaulted on unstable USB hardware (SIGSEGV, no Python exception possible). Added a 30 s TTL cache in `SDRController._enumerate_devices()`; returns stale cache on failure instead of crashing. `open()` uses `force=True` to refresh when actually opening the device.
- **SSB focus_hits default mismatch** — `ssb_focus_hits_required` API default was 1 while the engine expected 2, causing premature SSB event emission on weak signals. Fixed default to 2 in `scan.py`.
- **SSB SNR threshold too conservative** — `MARKER_MIN_SNR_DB` was 10.0 dB, suppressing valid SSB detections on typical HF noise floors. Lowered to 8.0 dB (one S-unit above noise floor).
- **SSB spectrum hardcoded min hits** — `max(2, state.marker_min_hits)` in `spectrum.py` overrode the configured threshold; removed the hardcode so the configured value is used directly.
- **SSB marker TTL too short** — frontend TTL was 15 s (too fast for conversational SSB); raised to 20 s. Focus-validation passes also corrected from 1 to 2 in `app.js`.

## v0.8.0 - 2026-03-22

### Added
- **SSB Voice Signature Detection** — real-time SSB voice detection via spectral analysis with 15-second hold validation. Confirmed voice events are displayed as "Voice Signature" in the Events card.
- **Whisper ASR pipeline** — OpenAI Whisper integration (model "base") for speech-to-text on SSB audio. Includes RMS silence check, `no_speech_prob` filter, and known-hallucination word list. Prepared for transceiver audio input (FT-991A / IC-7300 via USB).
- **ASR admin controls** — enable/disable ASR from the Admin panel; dedicated Save ASR button.
- **SNR minimum gate** — events below 6 dB SNR are suppressed (one S-unit above noise floor, practical readability threshold).
- **SSB Callsign Detected filter** — Events card dropdown option to show only events with a valid amateur callsign identified.
- **IARU Region 1 band calibration tests** — automated validation of SSB+CW scan bounds for all HF bands.
- **SSB candidate-focus hold mode** — 15-second frequency hold to confirm persistent SSB activity before emitting an event.

### Changed
- **SSB occupancy events suppressed** — in SSB decoder mode, raw occupancy events are no longer saved or broadcast; only confirmed Voice Signature events from the hold-validation pipeline are emitted. Reduces event noise from ~100/min to ~5/90s.
- Propagation score and band summary moved above the globe map in the Propagation Map card for better visibility.
- SSB events without an identified callsign now display a "Voice Signature" badge instead of "callsign".
- Waterfall marker semantics corrected: occupancy shown as SSB_TRAFFIC, confirmed callsign as SSB.
- Persistent Butterworth filter state (`sosfilt_zi`) for continuous SSB demodulation across chunks.

### Fixed
- Occupancy detection decoupled from WebSocket connections — events are generated even when no browser is connected.
- Mega-segment pre-filter prevents occupancy detections outside scan band boundaries.
- Missing import crash in occupancy detection loop resolved.
- FSK/PSK filter added to prevent false SSB detections on digital mode frequencies.
- Whisper ASR decoupled from `ssb_focus` validation — fire-and-forget audio feed.
- Dual occupancy insertion path (events.py + decoders.py) unified — eliminated duplicate event flood.

## v0.7.1 - 2026-03-15

### Added
- Graphical installer (`install.sh`) — interactive whiptail TUI that guides the user through the full setup: system packages, optional RTL-SDR Blog v4 driver build, Python virtual environment, admin account creation (bcrypt, stored in SQLite), and systemd service activation. No manual steps required after `git clone`.

## v0.7.0 - 2026-03-15

### Changed
- Platform target refined to Linux PC and Raspberry Pi — the software is now focused on native Linux deployments (Ubuntu/Debian, Linux Mint, Raspberry Pi OS 64-bit).
- Install guides updated with complete RTL-SDR v4 driver instructions (build from `rtlsdrblog/rtl-sdr-blog`, kernel module blacklist, udev rules).
- Documentation cleanup: removed stale session reports and outdated internal references; corrected `sqlite_schema.sql` (missing columns) and `websocket_spec.md` (missing `/ws/logs` channel).

## v0.6.3 - 2026-03-15

### Fixed
- Waterfall decoded-marker TTL now per-mode and correctly scoped to a single band/mode session (no band-count factor, no cross-mode mixing):
  - FT8: 45 s (3 × 15 s window)
  - FT4: 23 s (3 × 7.5 s window)
  - WSPR: 360 s (3 × 120 s window)
  - CW/CW_CANDIDATE DSP markers: 45 s (1.5 × 30 s dwell, aligned to backend `cw_marker_ttl_s`)
  - Callsign proximity cache: 45 s (aligned to FT8)
- Previous TTL values were inflated by a spurious ×6-bands factor and incorrectly combined FT8+FT4 window times — both errors removed.

### Fixed
- CI test fragility in `test_storage_db_metrics.py`: replaced hardcoded timestamps from `2026-03-06` with dynamic relative timestamps (`datetime.now(timezone.utc) - timedelta(minutes=X)`) so the SSB metrics tests always fall within the query window regardless of when they run.

## v0.6.1 - 2026-03-15

### Added
- Waterfall transition overlay covering the full spectrum+waterfall area (spectrum canvas and waterfall canvas are now wrapped in a common `waterfall-area` container; the overlay is positioned relative to it).
- Improved transition overlay visual design: dual-ring counter-rotating spinner, fade-in entry animation, pulsing message text, and a gradient dark backdrop with stronger blur.

### Changed
- All user-facing strings (toasts, status messages, log lines) translated to English — no more Portuguese in the UI.
- Retention system: count-based threshold raised to 500,000 events; when triggered, all events are exported and only the 50,000 most recent are kept (`RETENTION_KEEP_EVENTS` env var, default 50 000). Age-based purge (30 days) still runs independently.
- Waterfall status line colour changed to yellow (`#facc15`) for better contrast against the dark waterfall background.
- Propagation Map no longer shows an "Unknown" band entry — events without a `band` value are now silently skipped in the summary builder.

### Fixed
- `modeFilter is not defined` JS error when switching mode during an active scan — the variable was never declared; replaced with the correct `eventsSearchModeInput` in four call sites (`startScan`, `syncScanState`, mode button handler).
- "No live spectrum data available" error appearing in preview/idle mode (no scan running) — the fallback timer and WebSocket error handlers now only show the error when `isScanRunning` is `true`.
- Waterfall not centering on the correct mode segment after a live band switch — `lastSpectrumFrame` is now cleared between `stopScan` and `startScan` in `switchBandLive` so `recenterWaterfallForMode` uses the new band's frequency range.
- Structured log configuration extracted to `backend/app/log_config.py`, fixing log formatting on startup.

## v0.6.0 - 2026-03-14

### Added
- Session-based authentication stored in SQLite, with login, logout, and session validation via cookie instead of browser Basic Auth prompts.
- Frontend auth bootstrap that validates the session on reload and only starts protected streams after authentication is confirmed.
- Scan context summary in the main UI showing the active scan range and, when CW is selected, the active CW decoder segment.

### Changed
- CW decoder 20 m segment corrected to `14.000-14.070 MHz`.
- CW mode changes during an active scan now start the CW decoder with the correct subsegment for the current band.
- Logout control restyled as a proper status chip and the login modal inputs restyled for readable black-on-white entry.

### Fixed
- Removed `WWW-Authenticate` prompts that were causing browser-native auth popups.
- Waterfall and protected WebSocket/data startup now happen after successful login, avoiding manual reload after authentication.
- WebSocket authentication now accepts the authenticated session cookie, keeping logs, events, spectrum, and status streams aligned with the UI login state.

## v0.5.0 - 2026-03-14

### Added

#### CW Decoder — Módulo Completo
- **`backend/app/decoders/cw/`** — decoder Morse puro Python (sem binários externos):
  - Bandpass Butterworth 4ª ordem (300–900 Hz)
  - Extracção de envelope via transformada de Hilbert + média móvel
  - Binarização automática com threshold estilo Otsu
  - Análise temporal: run-length encode → dit estimation → WPM = 1200/dit_ms
  - Tabela Morse completa com lookup de indicativos via regex
  - Confidence scoring: `0.5×char + 0.3×wpm + 0.2×length`
  - Suporte para CW de alta velocidade (contest, até 60+ WPM)
  - SNR e WPM configuráveis com validações
- **`backend/app/decoders/cw_sweep.py`** — `CWSweepDecoder` para varrimento de banda:
  - Sweep guiado por FFT com step configurável (default 6500 Hz)
  - Dwell time ajustável (default 30 s)
  - Detecção multi-peak com rejeição near-Nyquist
  - Diagnósticos de produção integrados
- **`backend/app/decoders/cw_session.py`** — `CWDecoderSession` para monitorização contínua:
  - Feed IQ em tempo real com janela deslizante
- **Integração API**:
  - CW decoder integrado em `/api/scan/mode` com start/stop automático
  - Auto-start ao arranque da aplicação
  - Exclusão mútua entre CW e FT decoders (um activo de cada vez)
  - Eventos de texto CW emitidos mesmo sem callsign + campos de ocupação

#### CW no Frontend
- Controlos CW sweep no painel de scan (step Hz, dwell s)
- Marcadores CW injectados no waterfall como `mode_markers`
- Botão CW corrigido: já não fica sempre seleccionado após parar o scan

#### RTL-SDR V4 Support
- **`backend/app/sdr/controller.py`**:
  - Detecção automática de RTL-SDR V4 (tuner R828D)
  - V4 usa upconverter integrado — não aplica direct sampling para HF
  - Desactivação de hardware AGC para melhor descodificação de sinais fracos
- **`backend/app/api/scan.py`**:
  - Preview scan bounds configuráveis via env vars (`PREVIEW_START_HZ`, `PREVIEW_END_HZ`)
  - Limpeza de scan bounds stale ao parar
  - Estado de scan correcto durante modo preview

### Fixed

#### WSPR
- Frequências dial WSPR corrigidas para IARU Região 1
- Fix de OOM (Out-of-Memory) em janelas WSPR longas
- Interrupção da janela WSPR quando a banda muda mid-scan
- Abort da janela WSPR quando o modo muda durante slot wait
- Reset de estado parked no início do scan + reavaliação de dial freq após slot wait

#### CW
- 3 bugs críticos que causavam zero eventos CW descodificados
- Degradação Butterworth near-Nyquist + detecção multi-peak
- Default dwell corrigido para 30s; leitura de `cw_dwell_s`/`cw_step_hz` do scan payload
- Deadlock no event loop resolvido (USB open)
- Revert de park do scan engine durante CW decoder activo (abordagem abandonada)

#### Frontend / UX
- Marcadores WSPR agora visíveis no waterfall (pipeline DSP occupancy)
- Botão CW no frontend: estado correcto após scan stop
- Parâmetro duplicado removido no events endpoint (legacy)

### Changed

#### Layout & UX
- VFO display maior com fontes aumentadas
- Status movido para a barra VFO abaixo do SNR
- Signal Quality reposicionado junto ao botão GO
- Largura fixa para `vfo-goto-group` (elimina layout shift)
- Altura fixa para status inline display
- Linhas de banda com cores vibrantes e maior opacidade
- Onboarding overlay: wrapper element em falta adicionado
- Default waterfall zoom: 4x com vista centrada (revertido para 1x na primeira visita)

#### Mapa de Propagação
- Velocidade de drag do globo reduzida (0.5 → 0.25)
- Globe SVG preenche altura do card (100%/100%, `getBoundingClientRect`)
- Card Propagation Map mesma altura que Events
- Botões de controlo maiores (30 → 40px), ícones substituídos (reset=↻, fullscreen=⤢)
- Removido círculo de glow atmosférico
- Raio de glow actualiza correctamente com zoom

### Dependencies
- `scipy` adicionado a `requirements.txt` (necessário para CW decoder)

---

## v0.4.0 - 2026-02-26

### Added

#### 3D Propagation Globe
- **`frontend/map.js`** (347 linhas) — globo 3D interativo com `d3.geoOrthographic`:
  - Drag-to-rotate: arrastar roda o globo em qualquer direção
  - Scroll-to-zoom: roda do rato aumenta/diminui `proj.scale`
  - Botões overlay: `+` zoom in, `−` zoom out, `⌂` reset, `⛶` fullscreen
  - Double-click: repõe rotação centrada na estação
  - Arcos de grande-círculo via GeoJSON `LineString` (clipping automático pelo D3)
  - `d3.geoDistance` oculta dots no hemisfério oposto
  - Gradiente radial SVG para efeito de profundidade oceânica
  - Halo de atmosfera (círculo translúcido à volta do globo)
  - Legenda de bandas (cores por banda — paleta HF/VHF standard)
  - Tooltip `position:fixed` com callsign, país, banda, SNR, distância
  - Modal fullscreen Bootstrap (`modal-fullscreen`) com re-render ao abrir
  - Auto-refresh a cada 60 segundos
  - Todos os assets servidos localmente — funciona offline
- **`backend/app/api/map.py`** — `GET /api/map/contacts?window_minutes=60&limit=500`
  - Lê config da estação (callsign, locator Maidenhead)
  - Resolve cada callsign para entidade DXCC via longest-prefix-match
  - Calcula distância estação↔contacto via haversine
- **`backend/app/dependencies/helpers.py`** — novas funções:
  - `callsign_to_dxcc(callsign)` — longest-prefix-match contra 4528 prefixos DXCC
  - `maidenhead_to_latlon(grid)` — converte locator Maidenhead 4/6 chars para (lat, lon)
  - `haversine_km(lat1, lon1, lat2, lon2)` — distância em km entre dois pontos
- **`prefixes/dxcc_coords.json`** — base de dados DXCC gerada de cty.dat (AD1C):
  - 346 entidades DXCC com nome, continente, zona CQ, lat/lon
  - 4528 prefixos no índice de lookup
- **`prefixes/cty.dat`** — ficheiro fonte DXCC (AD1C, versão 25 Feb 2026, 99 KB)
- **`scripts/build_dxcc_coords.py`** — script de geração de `dxcc_coords.json` a partir de `cty.dat`
- **Assets frontend locais** (sem CDN):
  - `frontend/lib/d3.min.js` — D3.js v7.9.0 UMD (274 KB)
  - `frontend/lib/topojson.min.js` — TopoJSON Client 3.0.2 (21 KB)
  - `frontend/lib/countries-110m.json` — Natural Earth 110m em formato TopoJSON (106 KB)

#### Search Events Modal
- Modal Bootstrap dark com campos: Callsign (LIKE parcial), Mode, Band, Min SNR
- `AbortController` cancela fetches anteriores em voo (evita race conditions)
- Occupancy events filtrados — resultados mostram apenas eventos com callsign
- SNR colorido por valor em cada resultado

#### Propagation Card
- Card movido para `col-12 col-lg-6` ao lado do card Events
- Score colorido dinamicamente: `Poor`=red / `Fair`=yellow / `Good|Excellent`=green

### Fixed
- `build_propagation_summary()` — resposta reestruturada de dict plano para dict aninhado
  (`data.overall.score`, `data.event_count`) para compatibilidade com o frontend
- Rate limit da API de events: 30 → 300 req/min (evitava timeout em pesquisa rápida)
- Search modal z-index: modal movido para fora de `</main>`

### Libraries Added
| Biblioteca | Versão | Uso |
|------------|--------|-----|
| D3.js UMD | 7.9.0 | Projeção ortográfica, drag, gradientes SVG, geodésica |
| TopoJSON Client | 3.0.2 | Deserialização de topologia vectorial (países) |
| Natural Earth 110m | — | Geometria dos países em TopoJSON |

### Technical Notes
- A projeção `geoOrthographic` com `clipAngle(90)` garante que apenas o hemisfério
  frontal é renderizado — D3 recorta automaticamente arcos e países no limbo.
- O globo não usa `d3.zoom()` (que faz transform CSS); em vez disso manipula
  diretamente `proj.rotate()` e `proj.scale()` e chama `redraw()` a cada evento,
  para garantir que os arcos geo e a clipAngle são sempre recalculados corretamente.
- O endpoint `/api/map/contacts` resolve callsigns em tempo real sem cache —
  o lookup DXCC é O(n·k) onde k ≤ 6 (comprimento máximo do prefixo).

---

## v0.3.1 - 2026-02-23

### Added
- **5 Novos Endpoints API**:
  - `GET /api/events/export/csv` - Export de eventos em formato CSV com rate limiting (10 req/min)
  - `GET /api/events/export/json` - Export de eventos em formato JSON com rate limiting (10 req/min)
  - `POST /api/decoders/start/{decoder_type}` - Endpoint unificado para iniciar decoders (internal-ft, external-ft)
  - `POST /api/decoders/stop/{decoder_type}` - Endpoint unificado para parar decoders (internal-ft, external-ft)
  - `GET /api/admin/audio/detect` - Detecção automática de dispositivos e configuração de áudio

### Changed
- Limite máximo de 10.000 eventos por operação de export
- Rate limiting diferenciado: 10 req/min para exports, 30 req/min para queries normais
- Respostas API padronizadas com `{"status": "ok", ...}`
- Arquivos modificados:
  - `backend/app/api/events.py` - +115 linhas (302 total)
  - `backend/app/api/decoders.py` - +96 linhas (599 total)
  - `backend/app/api/admin.py` - +23 linhas (235 total)

### Enhanced
- Documentação completa (docstrings) em todos os novos endpoints
- Suporte a aliases de tipos de decoder (internal-ft, internal_ft, ft-internal, ft_internal)
- Validação de tipos de decoder com mensagens de erro descritivas (HTTPException 400)
- Autenticação opcional nos endpoints de export (`optional_verify_basic_auth`)
- Autenticação obrigatória no admin (`verify_basic_auth`)
- Formatação CSV otimizada com PlainTextResponse

### Testing
- **Validação de Novos Endpoints**: 10/10 testes passaram (100%)
- **Backend Tests**: 37/37 testes pytest passaram (100%)
- **Frontend Tests**: 17/17 testes passaram (100%)
- **Integração**: 47 rotas API registradas, todos endpoints frontend compatíveis
- **Sintaxe Python**: Validada em todos os arquivos modificados
- Scripts de teste criados:
  - `test_new_endpoints.sh` - Validação dos 5 novos endpoints
  - `validate_api_endpoints.sh` - Análise completa da API

## v0.3.0 - 2026-02-23

### Added
- **Frontend Modularization**: Created ES6 modules for better code organization:
  - `modules/config.js` - Constants and configuration
  - `modules/dom.js` - Centralized DOM element references
  - `modules/api.js` - REST API client with authentication
  - `modules/ui.js` - UI utilities (toasts, formatters, helpers)
  - `modules/websocket.js` - WebSocket manager with auto-reconnection
- **CI/CD Pipeline**: GitHub Actions workflow for automated testing and quality checks
  - Backend tests on Python 3.10, 3.11, 3.12
  - Frontend tests on Node.js 18, 20, 22
  - Code quality checks with Ruff, Black, and mypy
  - Security audits with pip-audit and safety
- **Type Hints**: Added comprehensive type hints to core Python modules:
  - `scan/engine.py` - Full type annotations for ScanEngine class
  - `streaming.py` - Type hints for encoding/decoding functions
- **Frontend Tests**: Created `package.json` for proper test management
- **Documentation**: Added README files for frontend modules and GitHub workflows

### Fixed
- **Critical Bug**: Fixed uninitialized `_parked_event` in `scan/engine.py`
  - Added proper asyncio.Event initialization in `__init__`
  - Improved park/unpark flow with event-based synchronization
- **File Handle Leak**: Enhanced `stop_async()` with proper exception handling
  - Guaranteed cleanup of file handles even on errors
  - Added proper task cancellation handling

### Changed
- **Improved Error Handling**: Better exception handling in critical paths
- **Code Quality**: Backend already refactored into modular API structure
- **Testing**: All 37 backend tests passing, 17 frontend tests passing

### Technical Debt Paid
- Resolved `_parked_event` RuntimeError risk
- Improved async cleanup in scan engine
- Better separation of concerns in frontend code

## v0.2.5 - 2026-02-22

### Changed
- Removed Fake waterfall mode from frontend controls and runtime behavior.
- Waterfall now stays in LIVE mode and does not render simulated spectrum data.

### Fixed
- Replaced simulated fallback rendering with a generic user-facing no-data message when no SDR device is available or live frames become stale.
- Improved readability of the waterfall no-data message with larger, centered, high-contrast presentation.

## v0.2.0 - 2026-02-21

### Added
- Configuration loader and schema validation for scan and region profile inputs.
- DSP occupancy improvements with mode heuristics and confidence scoring.
- Decoder pipelines for WSJT-X UDP, Direwolf KISS, CW parsing, and SSB ASR controlled vocabulary.
- WebSocket spectrum streaming backpressure handling and `delta_int8` compressed frames.
- WebGL waterfall rendering with fallback plus JSON/PNG export controls in frontend.
- Persistent export metadata and file rotation workflow in SQLite storage layer.
- IQ-sample QA harness with fixture-driven assertions.
- DSP benchmark tool for cross-platform performance comparison.
- Deployment packaging assets for Linux (`systemd`) and Windows service installation.

### Changed
- Same-origin frontend serving integrated into backend runtime flow.
- Decoder process management supports optional autostart and clean shutdown lifecycle.
- Documentation expanded for installation, operations, storage schema, and websocket contract updates.
- Repository hygiene improved with `.gitignore` for runtime artifacts.

### Fixed
- WSJT-X text parsing now correctly extracts `grid` and `report` from payload tokens.
- Decoder status visibility improved through runtime process state fields.
- Runtime validation paths aligned with current API/event payload behavior.
