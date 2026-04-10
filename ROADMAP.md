<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
Last update: 2026-04-10
-->

# 🗺️ ROADMAP — 4ham-spectrum-analysis

> **Also available in:** [Português](ROADMAP_PT.md)

**Current Version**: v0.10.0  
**Last Update**: 2026-04-10  
**Status**: 🟢 Production-Ready (unstable branch)

---

## 📊 PROJECT OVERVIEW

### Current State
- ✅ Modular backend (FastAPI, 58 Python modules, 203 tests — 100% pass)
- ✅ Frontend with ES6 modules (app.js + 10 modules in `modules/` and `utils/`)
- ✅ 56+ API routes
- ✅ Interactive TUI installer (whiptail) — Ubuntu/Debian/Mint/RPi OS
- ✅ SSB Voice Signature Detection with hold-validation pipeline
- ✅ Whisper ASR pipeline (FT-991A / IC-7300 USB)
- ✅ Propagation Map with 3D globe & 3-formula scoring (Digital/CW/SSB)
- ✅ Academic Analytics dashboard with multi-format export (CSV/XLSX/JSON)
- ✅ Scan Rotation scheduler (multi-band/mode cycling)
- ✅ Decoders: FT8, FT4, WSPR, CW, SSB integrated
- ✅ Callsign ITU validation (letter-start + digit-start patterns)
- ✅ Desktop launcher shortcut (GNOME/Cinnamon/XFCE/KDE/MATE/LXQt)
- ✅ Check for Updates button (git pull + auto-restart)
- ✅ SSB BW cap at 2800 Hz (phantom event elimination)
- ✅ SSB focus hold system (auto formula span÷15k, max 16 holds/pass)
- ✅ Documentation: install, user manuals (PT/EN), help.html, propagation scoring (PT/EN)
- ⚠️ Frontend app.js still 4230 lines (partially modularised)
- ⚠️ Middleware directory placeholder (only `__init__.py`)

### Version History
| Version | Date | Milestone |
|---------|------|-----------|
| v0.3.1 | 2026-02-23 | Modular backend, 54 tests, CI/CD |
| v0.6.0 | 2026-03-14 | Waterfall WebGL, retention, i18n EN |
| v0.7.0 | 2026-03-15 | Linux-only target, TUI installer |
| v0.8.0 | 2026-03-22 | SSB Voice Signature, Whisper ASR, SNR gate |
| v0.8.3 | 2026-04-02 | VOICE DETECTED waterfall markers, mode-filtered events |
| v0.8.5 | 2026-04-03 | Academic Analytics dashboard |
| v0.8.7 | 2026-04-05 | Desktop launcher, Check for Updates |
| v0.9.0 | 2026-04-06 | 3-formula propagation scoring, multi-format export |
| v0.10.0 | 2026-04-08 | Scan Rotation scheduler, phantom mode fix |

---

## ✅ COMPLETED (since v0.8.3)

### SSB Signal Quality Hardening ✅ (unstable, 2026-04-10)
- SSB marker flood fix — 60 s debounce + SNR ≥ 8 dB gate
- Voice marker cache preserved before debounce
- Backend `band_display` updated after SSB subband clipping
- Focus hold coverage improvement (hold_ms 15→10 s, auto formula span÷15k, max 16)
- Phantom SSB event elimination — BW cap at 2800 Hz across all 4 filtering points (pipeline, events, decoders, helpers)

### Scan Rotation ✅ (v0.10.0)
- Automated multi-band/mode cycling with configurable dwell time
- Loop option and live countdown status bar
- Full UI panel with slot editor and WebSocket sync

### Academic Analytics ✅ (v0.8.5 – v0.9.0)
- Full analytics dashboard with activity timeline, band distribution, heatmap, propagation map
- 3-formula propagation scoring (Digital/CW/SSB with tailored SNR normalisation)
- Multi-format export (CSV/XLSX/JSON), 1 h / 12 h presets
- Callsign ITU validation

### Phantom Mode Fix ✅ (v0.10.0)
- Occupancy events forced to match active decoder mode
- Confirmed band modes SQL time-scoped to analysed period

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

**Current state**: 10 modules already extracted (`waterfall.js`, `api.js`, `websocket.js`, `config.js`, `constants.js`, `dom.js`, `ui.js`, `utils.js`, `presets.js`). Main orchestrator still too large.

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

### 4. Custom Middleware Implementation 🛡️
**Goal**: Add middleware for logging, metrics, and security

**Tasks**:
- [ ] 4.1. RequestLoggingMiddleware (structured per-request logs)
- [ ] 4.2. SecurityHeadersMiddleware (HSTS, CSP, X-Frame-Options)
- [ ] 4.3. CORSMiddleware refined (production-ready, origin whitelist)
- [ ] 4.4. RateLimitMiddleware (abuse protection)
- [ ] 4.5. Environment-based configuration (dev/staging/prod)
- [ ] 4.6. Middleware tests
- [ ] 4.7. Documentation

**Benefit**: Observability, security, compliance

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
**Goal**: Production observability

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

#### 8.3. Scan Scheduler
- [ ] Schedule scans by hour/day
- [ ] Programmable scan profiles
- [ ] Important event notifications

#### 8.4. Mobile-Responsive UI
- [ ] Responsive layout for tablets
- [ ] Smartphone-optimised UI
- [ ] Touch-friendly controls

#### 8.5. Themes & Customisation
- [ ] Dark/Light theme switcher
- [ ] Waterfall colour customisation
- [ ] Configurable layout (drag-and-drop panels)

---

### 9. Infrastructure Optimisations 🏗️

#### 9.1. Docker Compose Stack
- [ ] Optimised multi-stage Dockerfile
- [ ] Complete docker-compose.yml
- [ ] Persistence volumes
- [ ] Health checks

#### 9.2. Automated Backups
- [ ] Automatic SQLite backups
- [ ] Backup rotation (7 days, 4 weeks)
- [ ] Restore scripts
- [ ] Integrity verification

---

### 10. Security Enhancements 🔒

#### 10.1. OAuth2/JWT Authentication
- [ ] Replace Basic Auth with JWT
- [ ] Refresh tokens
- [ ] Role-based access control (RBAC)
- [ ] Session management

#### 10.2. Security Audit
- [ ] Vulnerability scan (OWASP Top 10)
- [ ] Dependency updates
- [ ] Penetration testing
- [ ] Security headers audit

#### 10.3. Advanced Rate Limiting
- [ ] Per-user rate limits
- [ ] IP-based throttling
- [ ] Distributed rate limiting (Redis)
- [ ] Adaptive rate limiting

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
