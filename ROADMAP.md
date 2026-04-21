<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
Last update: 2026-04-21
-->

# 🗺️ ROADMAP — 4ham-spectrum-analysis

> **Also available in:** [Português](ROADMAP_PT.md)

**Current Version**: v0.12.4  
**Last Update**: 2026-04-21  
**Status**: 🟢 Production-Ready (main branch)

---

## 📊 PROJECT OVERVIEW

### Current State
- ✅ Modular backend (FastAPI, 58 Python modules, 203 tests — 100% pass)
- ✅ Frontend with ES6 modules (app.js + 9 modules in `modules/` and `utils/`)
- ✅ 64 API routes
- ✅ Interactive TUI installer (whiptail) — Ubuntu/Debian/Mint/RPi OS
- ✅ SSB Voice Signature Detection with hold-validation pipeline
- ✅ Whisper ASR pipeline (FT-991A / IC-7300 USB)
- ✅ QTH-Centric Propagation Map: DR2W-style 3-layer solar-shaped zones, NOAA SWPC ionospheric model (foF2, D-layer, band status), ionospheric sidebar, Ctrl+scroll zoom, sessionStorage persistence
- ✅ Propagation Map with 3D globe & 3-formula scoring (Digital/CW/SSB)
- ✅ Academic Analytics dashboard with multi-format export (CSV/XLSX/JSON)
- ✅ Scan Rotation scheduler (multi-band/mode cycling with dwell time, loop, presets)
- ✅ Decoders: FT8, FT4, WSPR, CW, SSB, APRS integrated
- ✅ Callsign ITU validation + DXCC prefix lookup (4528 prefixes)
- ✅ Session-cookie authentication with bcrypt (replaced Basic Auth in v0.6.0)
- ✅ Security headers (X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy)
- ✅ CORS middleware (env-var-driven origins, credentials support)
- ✅ Rate limiting via slowapi (global + per-route: 300/min events, 10/min exports)
- ✅ Data retention system (age-based + count-based purge, auto-export before deletion)
- ✅ Log rotation (RotatingFileHandler, 10 MB × 5 backups)
- ✅ Region profile system (YAML, JSON schema validation, CLI flag)
- ✅ Desktop launcher shortcut (GNOME/Cinnamon/XFCE/KDE/MATE/LXQt)
- ✅ Check for Updates button (git pull + auto-restart)
- ✅ SSB BW cap at 2800 Hz (phantom event elimination)
- ✅ SSB focus hold system (auto formula span÷15k, max 16 holds/pass)
- ✅ Responsive CSS layout (Bootstrap + media queries at 991 px / 575 px)
- ✅ Toast notification system (success/error/warning/info)
- ✅ Documentation: install, user manuals (PT/EN), help.html, propagation scoring (PT/EN)
- ⚠️ Frontend app.js still 4230 lines (partially modularised)
- ⚠️ Middleware implementations live in `main.py`, not in the `middleware/` package

### Version History
| Version | Date | Milestone |
|---------|------|-----------|
| v0.3.1 | 2026-02-23 | Modular backend, 54 tests, CI/CD |
| v0.5.0 | 2026-03-10 | CW decoder (Butterworth BPF, Hilbert envelope, Morse table, sweep) |
| v0.6.0 | 2026-03-14 | Waterfall WebGL, data retention, session-cookie auth, i18n EN |
| v0.7.0 | 2026-03-15 | Linux-only target, TUI installer |
| v0.8.0 | 2026-03-22 | SSB Voice Signature, Whisper ASR, SNR gate |
| v0.8.3 | 2026-04-02 | VOICE DETECTED waterfall markers, mode-filtered events |
| v0.8.5 | 2026-04-03 | Academic Analytics dashboard |
| v0.8.7 | 2026-04-05 | Desktop launcher, Check for Updates |
| v0.9.0 | 2026-04-06 | 3-formula propagation scoring, multi-format export, callsign ITU validation |
| v0.10.0 | 2026-04-08 | Scan Rotation scheduler, phantom mode fix |
| v0.11.1 | 2026-04-10 | SQLite concurrency fix, SSB signal quality hardening, production stabilisation |
| v0.12.4 | 2026-04-18 | Academic Analytics enriched export (13 new fields), human-readable column headers |
| v0.12.3 | 2026-04-17 | Preset Scheduler (time-of-day auto-rotation), overlap validation, auto-start on boot |
| v0.12.2 | 2026-04-12 | SNR KPI split (Digital vs CW/SSB), dashboard cleanup, external embedding docs |
| v0.12.1 | 2026-04-12 | QTH-Centric Propagation Map redesign, NOAA SWPC ionospheric model, ionospheric sidebar |

---

## ✅ COMPLETED (since v0.8.3)

### SSB Signal Quality Hardening ✅ (v0.11.1)
- SSB marker flood fix — 60 s debounce + SNR ≥ 8 dB gate
- Voice marker cache preserved before debounce
- Backend `band_display` updated after SSB subband clipping
- Focus hold coverage improvement (hold_ms 15→10 s, auto formula span÷15k, max 16)
- Phantom SSB event elimination — BW cap at 2800 Hz across all 4 filtering points (pipeline, events, decoders, helpers)

### Scan Rotation ✅ (v0.10.0)
- Automated multi-band/mode cycling with configurable dwell time
- Loop option and live countdown status bar
- Full UI panel with slot editor and WebSocket sync
- Rotation presets (save/load/delete)

### Academic Analytics ✅ (v0.8.5 – v0.9.0)
- Full analytics dashboard with activity timeline, band distribution, heatmap, propagation map
- 3-formula propagation scoring (Digital/CW/SSB with tailored SNR normalisation)
- Multi-format export (CSV/XLSX/JSON), 1 h / 12 h presets
- Callsign ITU validation + DXCC prefix lookup
- Enriched "All Events" export with 13 additional fields per event (DXCC entity, continent, code, lat/lon, power, confidence, crest, Doppler shift, source, grid locator, derived band, normalised mode)
- Human-readable column headers with measurement units across all export formats

### Phantom Mode Fix ✅ (v0.10.0)
- Occupancy events forced to match active decoder mode
- Confirmed band modes SQL time-scoped to analysed period

### Previously completed (up to v0.8.3)
- CW decoder subsystem (Butterworth BPF, Hilbert envelope, Morse table, CW sweep)
- APRS decoder (Direwolf KISS frame parsing, APRS line parser)
- Region profile system (YAML config, JSON schema, CLI `--region-profile-path`)
- Session-cookie authentication with bcrypt (login/logout/status endpoints)
- Security headers middleware (X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy)
- CORS middleware (env-var-driven origins via `CORS_ORIGINS`, toggle via `CORS_ENABLED`)
- Rate limiting via slowapi (global limiter + per-route limits)
- Data retention system (age + count purge, auto CSV export before deletion)
- Log rotation (RotatingFileHandler, configurable via `LOG_MAX_BYTES` / `LOG_BACKUP_COUNT`)
- Export file rotation (max 50 files, max 7 days age)
- Toast notification system (frontend)
- Responsive CSS layout (Bootstrap + media queries)
- `main_legacy.py` removed (architecture cleanup)

---

## 🎯 PRIORITY LEGEND

- 🔴 **HIGH** — Next 1–2 sprints, critical for quality or usability
- 🟡 **MEDIUM** — 2–4 sprints, important but not blocking
- 🟢 **LOW** — Backlog, nice-to-have

---

## 🔴 HIGH PRIORITY

### 1. Configurable SSB SNR Gate 🎛️
**Goal**: Make the SSB SNR threshold user-configurable so it adapts to each station's antenna/receiver setup

**Context**: The SSB event gate is hardcoded at 8 dB in 4 code points. With a good antenna (e.g. Prosistel PST-1524VC), 45% of events fall in the 8–10 dB range. A station with a modest antenna (wire, indoor) would have signals at 4–6 dB — the current gate would reject almost everything.

**Production data (2026-04-10)**: 1820 SSB events — 17.6% at 6–8 dB, 45.3% at 8–10 dB, max SNR 27.5 dB.

**Tasks**:
- [ ] 1.1. Add `ssb_snr_gate_db` to `state.py` (env var `SSB_SNR_GATE_DB`, default 8.0)
- [ ] 1.2. Replace all 4 hardcoded gates (8.0 dB) with `state.ssb_snr_gate_db`
  - `events.py` — voice marker cache gate
  - `events.py` — SSB event emission (post-debounce)
  - `events.py` — general occupancy SSB gate (6.0 dB → derive from gate)
  - `decoders.py` — SSB detector loop
- [ ] 1.3. Expose in `/api/settings` (GET/PUT)
- [ ] 1.4. Add control in frontend (Settings → SSB → SNR Gate)
- [ ] 1.5. Validation: range 3.0–20.0 dB
- [ ] 1.6. Unit tests (gate at 4, 8, 12 dB)
- [ ] 1.7. Documentation (install.md, help.html)

**Benefit**: Adapts to any antenna/receiver setup — fewer false positives on strong stations, weaker signals captured on modest setups

---

### 2. Real-Band SSB Validation 🎙️
**Goal**: Validate SSB thresholds with real antenna tests across bands

**Tasks**:
- [ ] 2.1. SSB scan 40 m during activity period (18–22 UTC)
- [ ] 2.2. SSB scan 20 m during activity period (10–16 UTC)
- [ ] 2.3. Measure marker rate (false vs legitimate) per minute
- [ ] 2.4. Measure time to first confirmed event
- [ ] 2.5. Test detection of short QSOs (3–5 s)
- [ ] 2.6. Adjust SNR gate via new configurable setting if needed
- [ ] 2.7. Merge unstable → main when validated

**Benefit**: Confidence in thresholds, safe merge to main

---

### 3. Frontend Modularisation (Phase 2) 📦
**Goal**: Continue refactoring app.js (still 4230 lines) into smaller ES6 modules

**Current state**: 9 modules already extracted (`waterfall.js`, `api.js`, `websocket.js`, `config.js`, `constants.js`, `dom.js`, `ui.js`, `utils.js`, `presets.js`). Main orchestrator still too large.

**Tasks**:
- [ ] 3.1. Extract `events.js` module (event table management)
- [ ] 3.2. Extract `controls.js` module (scan control panel)
- [ ] 3.3. Extract `charts.js` module (visualisations)
- [ ] 3.4. Extract `propagation.js` module (map and propagation)
- [ ] 3.5. Reduce app.js to orchestrator (<500 lines)
- [ ] 3.6. Update frontend tests
- [ ] 3.7. Validate full functionality post-migration

**Benefit**: Maintainability, testability, readability

---

### 4. Middleware Consolidation 🛡️
**Goal**: Move existing middleware from `main.py` into the `middleware/` package and add missing pieces

**Current state**: Security headers, CORS, and rate limiting are already implemented in `main.py` but not organised in the middleware package.

**Tasks**:
- [ ] 4.1. Move security headers middleware to `middleware/security.py`
- [ ] 4.2. Add missing HSTS and CSP headers
- [ ] 4.3. Move CORS config to `middleware/cors.py`
- [ ] 4.4. Move rate limiter to `middleware/ratelimit.py`
- [ ] 4.5. Add RequestLoggingMiddleware (structured per-request logs)
- [ ] 4.6. Environment-based configuration (dev/staging/prod)
- [ ] 4.7. Middleware tests
- [ ] 4.8. Documentation

**Benefit**: Code organisation, observability, complete security headers (HSTS, CSP)

---

## 🟡 MEDIUM PRIORITY

### 5. End-to-End (E2E) Tests 🧪
**Goal**: Add full integration tests

**Tasks**:
- [ ] 5.1. Setup Playwright or Cypress
- [ ] 5.2. Full scan flow tests
- [ ] 5.3. Export tests (CSV/JSON/XLSX)
- [ ] 5.4. Decoder management tests
- [ ] 5.5. Real-time WebSocket tests
- [ ] 5.6. Authentication tests
- [ ] 5.7. CI/CD integration
- [ ] 5.8. Screenshots on failure

---

### 6. Monitoring Dashboard 📈
**Goal**: Production observability beyond current logging

**Tasks**:
- [ ] 6.1. Prometheus/Grafana integration
- [ ] 6.2. System metrics (CPU, RAM, disk)
- [ ] 6.3. Application metrics (requests/s, latency)
- [ ] 6.4. Decoder metrics (events/min, avg SNR)
- [ ] 6.5. SDR metrics (sample rate, overflows)
- [ ] 6.6. Automated alerts (email/webhook)
- [ ] 6.7. Custom Grafana dashboard

---

### 7. Performance Optimisation 🚀
**Goal**: Improve throughput, reduce latency

**Tasks**:
- [ ] 7.1. Profile slow endpoints
- [ ] 7.2. SQLite query optimisation (indices)
- [ ] 7.3. Frequent data caching (optional Redis)
- [ ] 7.4. HTTP response compression (gzip/brotli)
- [ ] 7.5. WebSocket message batching
- [ ] 7.6. Lazy loading of historical data
- [ ] 7.7. Before/after benchmarks

---

## 🟢 LOW PRIORITY

### 8. New Features 🎁

#### 8.1. Multi-Device Support
- [ ] Simultaneous scan on multiple SDRs
- [ ] Multi-device data aggregation
- [ ] Multi-device management UI

#### 8.2. PSKReporter Integration
- [ ] Automatic spot submission to PSKReporter
- [ ] Callsign and locator configuration
- [ ] Rate limiting and validation

#### 8.3. Push Notifications
- [ ] Browser push notifications for important events (rare DX, new band opening)
- [ ] Configurable notification filters (by mode, band, callsign pattern)
- [ ] Email/webhook notification option

#### 8.4. Themes & Customisation
- [ ] Dark/Light theme switcher
- [ ] Waterfall colour customisation
- [ ] Configurable layout (drag-and-drop panels)

#### 8.5. Mobile UI Enhancements
- [ ] Tablet-optimised layout (landscape/portrait)
- [ ] Smartphone touch-friendly controls
- [ ] Progressive Web App (PWA) support

---

### 9. Infrastructure Optimisations 🏗️

#### 9.1. Docker Compose Stack
- [ ] Optimised multi-stage Dockerfile
- [ ] Complete docker-compose.yml
- [ ] Persistence volumes
- [ ] Health checks

#### 9.2. SQLite Backup & Restore
- [ ] Automated SQLite full-database backups (complementing existing event CSV auto-export)
- [ ] Restore scripts with integrity verification
- [ ] Scheduled backup rotation

---

### 10. Security Enhancements 🔒

#### 10.1. JWT Authentication
- [ ] Replace current session-cookie auth with JWT tokens
- [ ] Refresh tokens
- [ ] Role-based access control (RBAC)

#### 10.2. Security Audit
- [ ] Vulnerability scan (OWASP Top 10)
- [ ] Dependency updates
- [ ] Penetration testing

#### 10.3. Advanced Rate Limiting
- [ ] Per-user rate limits
- [ ] IP-based throttling
- [ ] Adaptive rate limiting

---

### 11. LoRa & Mesh Protocols 📡

> **Context**: LoRa operates in ISM bands (433 / 868 MHz), fully receivable with the existing RTL-SDR. No new hardware required for reception and analysis. Four phases in order of complexity and local traffic volume.

#### 11.1 LoRa APRS 🟡 MEDIUM
**Goal**: Receive and decode LoRa APRS frames on 433.775 MHz / 868.075 MHz and feed them into the existing APRS pipeline without modifications to parsers or UI.

**Architecture**: `lora_aprs.py` decoder following the `direwolf_kiss.py` pattern — launches `gr-lora_sdr` (GNU Radio) as an external process and reads decoded frames via pipe/socket. APRS payload format is identical to VHF; `parsers.py` is reused unchanged. DB stores frames with source field value `"lora"`.

**Tasks**:
- [ ] 11.1.1. Install and validate `gr-lora_sdr` with RTL-SDR on 433.775 MHz — confirm frame reception
- [ ] 11.1.2. Write `backend/app/decoders/lora_aprs.py` (model: `direwolf_kiss.py`)
- [ ] 11.1.3. Add 433.775 MHz and 868.075 MHz as band/source entries in config
- [ ] 11.1.4. Wire into `launchers.py` and `watchers.py`
- [ ] 11.1.5. Add `source` field to APRS DB schema (`"vhf"` / `"lora"`)
- [ ] 11.1.6. Frontend: source toggle in APRS view (VHF / LoRa / All)
- [ ] 11.1.7. Unit tests for LoRa APRS decoder
- [ ] 11.1.8. Documentation update (install.md, user_manual_en.md)

**Benefit**: Zero parser/UI changes — LoRa APRS stations appear on the existing map with a source badge. Unique combined VHF+LoRa coverage view.

---

#### 11.2 Meshtastic 🟢 LOW
**Goal**: Receive and decode Meshtastic mesh traffic on 869.525 MHz (EU868), extracting node positions, telemetry, and public channel messages.

**Architecture**: `meshtastic_decoder.py` — `gr-lora_sdr` for physical layer + official `meshtastic` Python lib (Protobuf) for frame parsing. Public channels decoded in clear; private DMs (ECC+AES) show metadata only (NodeID, RSSI, SNR, hop count).

**Tasks**:
- [ ] 11.2.1. Install `meshtastic` Python lib and validate Protobuf parsing against captured IQ
- [ ] 11.2.2. Write `backend/app/decoders/meshtastic_decoder.py`
- [ ] 11.2.3. Extract: NodeID, GPS position, battery telemetry, SNR, hop count, public messages
- [ ] 11.2.4. DB schema for Meshtastic nodes and messages
- [ ] 11.2.5. Frontend: Meshtastic nodes on APRS map (distinct icon) or new tab — decision pending
- [ ] 11.2.6. Unit tests
- [ ] 11.2.7. Documentation

**Benefit**: Meshtastic has active traffic across Europe; lib is official and well-documented. Position + telemetry data enriches coverage analysis.

---

#### 11.3 MeshCore 🟢 LOW
**Goal**: Receive and decode MeshCore mesh traffic (same ISM bands as Meshtastic).

**Architecture**: `meshcore_decoder.py` — requires protocol reverse engineering (spec is limited/partial). Physical layer via `gr-lora_sdr`. Deferred until Meshtastic phase is stable and MeshCore spec matures.

**Tasks**:
- [ ] 11.3.1. Research MeshCore protocol spec and open-source implementations
- [ ] 11.3.2. Assess decodability with available documentation
- [ ] 11.3.3. Write `backend/app/decoders/meshcore_decoder.py` if spec is sufficient
- [ ] 11.3.4. Frontend integration (shared with Meshtastic tab/view)
- [ ] 11.3.5. Tests and documentation

**Benefit**: Completes mesh protocol coverage. Lower priority due to smaller active community vs Meshtastic and limited protocol documentation.

---

#### 11.4 LoRaWAN Session Key Decryption 🟢 LOW
**Goal**: Allow users who own LoRaWAN devices to configure their session keys (NwkSKey + AppSKey) and decrypt captured payloads.

**Architecture**: Keys stored encrypted at rest (AES, derived from admin password — same pattern as `hash_password.py`). Never exposed via API in clear. Decrypt via `cryptography` lib (AES-128-CTR, LoRaWAN IV construction from DevAddr + FCnt).

**Tasks**:
- [ ] 11.4.1. Encrypted key store in DB (`lorawan_keys` table: DevEUI, DevAddr, NwkSKey_enc, AppSKey_enc)
- [ ] 11.4.2. Key management UI (add/remove/mask keys — shown as `••••••••` with reveal toggle)
- [ ] 11.4.3. Decrypt pipeline: DevAddr lookup → key retrieval → AES-128-CTR decrypt
- [ ] 11.4.4. MIC verification (NwkSKey)
- [ ] 11.4.5. API endpoints: `POST /api/lorawan/keys`, `DELETE /api/lorawan/keys/{dev_eui}`
- [ ] 11.4.6. Unit tests (known test vectors from LoRaWAN spec)
- [ ] 11.4.7. Security review and documentation

**Benefit**: Owners of private LoRaWAN deployments can view their own payload data within 4HAM. Only their data, with their keys.

---

## 🎯 SUCCESS METRICS

| Category | Metric | Target |
|----------|--------|--------|
| **Testing** | Test coverage | >80% |
| **API** | Response time (p95) | <100 ms |
| **UI** | Page load time | <2 s |
| **Security** | Critical vulnerabilities | 0 |
| **Uptime** | Availability | >99.5% |
| **Deploy** | Deploy time | <5 min |
| **Ops** | MTTR | <30 min |

---

## 📝 ARCHITECTURAL DECISIONS

1. **Keep Vanilla JS** — No framework (React/Vue) for now. Small project, excellent performance without it.
2. **SQLite in Production** — Acceptable for single-instance use. Simple backups, adequate performance.
3. **WebSocket Delta Compression** — Current strategy maintained (efficient, tested, functional).
4. **SSB BW Cap at 2800 Hz** — Standard SSB filter 2400 Hz + wide 2700 Hz + 100 Hz FFT margin. Signals above 2800 Hz are noise/interference.
5. **SSB SNR Gate at 8 dB** — Calibrated for good antenna setups. Will become configurable (see item 1).
6. **Session-Cookie Auth** — Replaced Basic Auth in v0.6.0. JWT upgrade planned (see item 10.1).
7. **LoRa/Mesh Decoder Pattern** — All LoRa/Mesh decoders follow the `direwolf_kiss.py` pattern: external GNU Radio process, pipe/socket communication, existing parsers reused where payload format matches. Meshtastic uses official Protobuf lib. MeshCore requires spec reverse engineering. LoRaWAN keys stored encrypted at rest, never exposed in clear via API.