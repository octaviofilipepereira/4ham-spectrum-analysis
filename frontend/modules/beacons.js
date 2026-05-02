// © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
/**
 * BeaconController — NCDXF/IARU Beacon Analysis frontend module
 *
 * Responsibilities:
 *  - Connect to /ws/beacons
 *  - Render and update the 18×5 beacon matrix (inline panel, not modal)
 *  - Drive the countdown to the next slot
 *  - Expose start() / stop() + currentFreqHz/currentCallsign getters for app.js
 */

const BANDS   = ["20m", "17m", "15m", "12m", "10m"];
const BEACONS = [
  { callsign: "4U1UN",  location: "New York, NY, USA" },
  { callsign: "VE8AT",  location: "Eureka, NU, Canada" },
  { callsign: "W6WX",   location: "Mt. Umunhum, CA, USA" },
  { callsign: "KH6RS",  location: "Maui, HI, USA" },
  { callsign: "ZL6B",   location: "Masterton, New Zealand" },
  { callsign: "VK6RBP", location: "Rolystone, WA, Australia" },
  { callsign: "JA2IGY", location: "Aichi, Japan" },
  { callsign: "RR9O",   location: "Novosibirsk, Russia" },
  { callsign: "VR2B",   location: "Hong Kong" },
  { callsign: "4S7B",   location: "Colombo, Sri Lanka" },
  { callsign: "ZS6DN",  location: "Pretoria, South Africa" },
  { callsign: "5Z4B",   location: "Nairobi, Kenya" },
  { callsign: "4X6TU",  location: "Tel Aviv, Israel" },
  { callsign: "OH2B",   location: "Lohja, Finland" },
  { callsign: "CS3B",   location: "Madeira, Portugal" },
  { callsign: "LU4AA",  location: "Buenos Aires, Argentina" },
  { callsign: "OA4B",   location: "Lima, Peru" },
  { callsign: "YV5B",   location: "Caracas, Venezuela" },
];

const SLOT_SECONDS = 10;
const SLOTS_PER_CYCLE = 18;

class BeaconController {
  constructor() {
    this._ws = null;
    this._reconnectTimer = null;
    this._reconnectDelay = 3000;
    this._running = false;           // scheduler running on backend
    this._beaconModeActive = false;  // user entered BEACON mode
    this._matrixData = {};           // key: `${slot}:${bandIdx}` → obs
    this._activeSlot = null;
    this._activeBand = null;
    this._countdownTimer = null;
    this._schedulerRunning = false;
    this._currentFreqHz = null;      // current slot frequency for VFO label
    this._currentCallsign = null;    // current slot beacon callsign

    this._matrixBody = document.getElementById("beaconMatrixBody");
    this._statusBadge = document.getElementById("beaconStatusBadge");
    this._countdown   = document.getElementById("beaconCountdown");
    this._startBtn    = document.getElementById("beaconStartBtn");
    this._stopBtn     = document.getElementById("beaconStopBtn");
    this._historyBody    = document.getElementById("beaconHistoryBody");
    this._historyHours   = document.getElementById("beaconHistoryHours");
    this._historyRefresh = document.getElementById("beaconHistoryRefresh");
    this._historyTimer   = null;
    this._bandBtns    = Array.from(document.querySelectorAll("[data-quick-band]"));
    // All mode buttons EXCEPT the BEACON one (that one stays clickable so the user can leave the mode)
    this._modeBtns    = Array.from(document.querySelectorAll('[data-quick-mode]')).filter(
      b => b.getAttribute("data-quick-mode") !== "BEACON"
    );
    this._beaconModeBtn = document.querySelector('[data-quick-mode="BEACON"]');
    // Other scan controls that must be disabled while BEACON owns the engine
    this._extraScanBtns = [
      document.getElementById("startScan"),
      document.getElementById("rotationToggleBtn"),
      document.getElementById("rotationPresetsMenuBtn"),
    ].filter(Boolean);

    this._bindUI();
    this._loadInitialMatrix();
    this._loadHistory();
    // Refresh history once per minute so the rolling window stays current.
    this._historyTimer = setInterval(() => this._loadHistory(), 60_000);
    this._connect();
  }

  // ── Initial matrix load (so a hard refresh keeps existing data) ────────────

  async _loadInitialMatrix() {
    try {
      const r = await fetch("/api/beacons/matrix", { cache: "no-store" });
      if (!r.ok) return;
      const data = await r.json();
      const matrix = data?.matrix;
      if (!Array.isArray(matrix)) return;
      for (let rowIdx = 0; rowIdx < matrix.length; rowIdx++) {
        const row = matrix[rowIdx] || [];
        for (let bandIdx = 0; bandIdx < row.length; bandIdx++) {
          const obs = row[bandIdx];
          if (obs) {
            this._matrixData[`${rowIdx}:${bandIdx}`] = obs;
          }
        }
      }
      this._renderMatrix();
    } catch (_) {}
  }

  // ── Recent activity heatmap (last N hours) ─────────────────────────────────

  async _loadHistory() {
    if (!this._historyBody) return;
    const hours = parseFloat(this._historyHours?.value || "2") || 2;
    try {
      const r = await fetch(`/api/beacons/heatmap?hours=${encodeURIComponent(hours)}`, { cache: "no-store" });
      if (!r.ok) return;
      const data = await r.json();
      this._renderHistory(data?.matrix, hours);
    } catch (_) {}
  }

  _renderHistory(matrix, hours) {
    if (!this._historyBody || !Array.isArray(matrix)) return;
    const now = Date.now();
    const rows = [];
    for (let s = 0; s < SLOTS_PER_CYCLE; s++) {
      const b = BEACONS[s];
      let cells = `<td class="beacon-callsign text-info" title="${b.callsign} — ${b.location}">${b.callsign}<span class="beacon-loc">— ${b.location}</span></td>`;
      const row = matrix[s] || [];
      for (let bi = 0; bi < BANDS.length; bi++) {
        cells += this._renderHistoryCell(row[bi], now);
      }
      rows.push(`<tr>${cells}</tr>`);
    }
    if (!rows.length) {
      this._historyBody.innerHTML = `<tr><td colspan="6" class="text-center text-muted small py-3">No data in last ${hours} h</td></tr>`;
      return;
    }
    this._historyBody.innerHTML = rows.join("");
  }

  _renderHistoryCell(cell, now) {
    if (!cell || !cell.total_slots) {
      return `<td class="beacon-cell text-secondary text-center"><span title="never sampled in window">·</span></td>`;
    }
    const det   = Number(cell.detections || 0);
    const total = Number(cell.total_slots || 0);
    if (det <= 0) {
      return `<td class="beacon-cell text-center" title="${total} slot(s) monitored, 0 detections">
        <small class="text-white">0/${total}</small>
      </td>`;
    }
    const snr   = (cell.max_snr_db != null) ? Number(cell.max_snr_db).toFixed(1) : "?";
    const dashes = Number(cell.max_dashes || 0);
    const meter  = renderBeaconMeter(dashes);
    let ago = "";
    if (cell.last_detected_utc) {
      const t = Date.parse(cell.last_detected_utc);
      if (!isNaN(t)) {
        const dt = Math.max(0, Math.round((now - t) / 1000));
        if (dt < 60) {
          ago = `${dt}s ago`;
        } else if (dt < 3600) {
          ago = `${Math.round(dt / 60)}m ago`;
        } else if (dt < 86400) {
          const h = Math.floor(dt / 3600);
          const m = Math.round((dt % 3600) / 60);
          ago = m > 0 ? `${h}h ${m}m ago` : `${h}h ago`;
        } else {
          const d = Math.floor(dt / 86400);
          const h = Math.round((dt % 86400) / 3600);
          ago = h > 0 ? `${d}d ${h}h ago` : `${d}d ago`;
        }
      }
    }
    const title = `Detected ${det}/${total} slots in window\nBest signal: ${dashes}/4 dashes, SNR ${snr} dB (100 W ref)\nLast: ${cell.last_detected_utc || "?"}`;
    return `<td class="beacon-cell beacon-cell--history-hit text-center" title="${title}">
      <small class="text-white">${meter} ${snr} dB<br>${det}/${total} &middot; ${ago}</small>
    </td>`;
  }

  // ── WS connection ──────────────────────────────────────────────────────────

  _connect() {
    if (this._ws) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/beacons`);
    this._ws = ws;

    ws.addEventListener("message", (ev) => {
      try { this._onMessage(JSON.parse(ev.data)); } catch (_) {}
    });
    ws.addEventListener("close", () => {
      this._ws = null;
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = setTimeout(() => this._connect(), this._reconnectDelay);
    });
    ws.addEventListener("error", () => {
      ws.close();
    });
  }

  _onMessage(msg) {
    // Lightweight debug — visible in browser console for diagnostics
    try { console.debug("[beacons] ws msg", msg.type, msg); } catch (_) {}
    switch (msg.type) {
      case "beacon_status":
        this._schedulerRunning = Boolean(msg.scheduler?.running);
        this._refreshStatusBadge();
        break;
      case "slot_start":
        this._onSlotStart(msg);
        break;
      case "observation":
        this._onObservation(msg);
        break;
    }
  }

  _onSlotStart(msg) {
    // Before switching the active marker, ensure the previously active
    // cell has SOME state — if no observation arrived (DSP overrun, lost
    // WS frame, etc.) we still want a red dot, not a blank cell.
    if (this._activeSlot != null && this._activeBand != null && this._activeBand >= 0) {
      const prevKey = `${this._activeSlot}:${this._activeBand}`;
      if (!this._matrixData[prevKey]) {
        this._matrixData[prevKey] = {
          detected: false,
          id_confirmed: false,
          dash_levels_detected: 0,
          snr_db_100w: null,
          _placeholder: true,
        };
      }
    }
    // Row is keyed by beacon_index (0..17 in the IARU/NCDXF order),
    // NOT by slot_index — the schedule is offset between bands.
    this._activeSlot = (msg.beacon_index != null) ? msg.beacon_index : (msg.slot_index % SLOTS_PER_CYCLE);
    this._activeBand = BANDS.indexOf(msg.band_name);
    // Clear any stale observation for the now-active cell so the cell
    // shows the ⏳ spinner until the new observation arrives.
    if (this._activeSlot != null && this._activeBand >= 0) {
      delete this._matrixData[`${this._activeSlot}:${this._activeBand}`];
    }
    this._currentFreqHz = msg.freq_hz;         // save for VFO label getter
    this._currentCallsign = msg.callsign;      // save for VFO label getter
    this._schedulerRunning = true;
    this._refreshStatusBadge();
    this._renderMatrix();
    this._startCountdown(msg.slot_start_utc);
    
    // Notify app.js to update VFO beacon label
    if (typeof window._syncBeaconContext === "function") {
      window._syncBeaconContext();
    }
  }

  _onObservation(obs) {
    // Match the row by beacon_index (the BEACONS array order). Using
    // slot_index % 18 here would shift one row per band (NCDXF rotates
    // by band_index on each band), causing 17m/15m/12m/10m to look
    // "incomplete".
    const rowIdx = (obs.beacon_index != null)
      ? obs.beacon_index
      : (obs.slot_index % SLOTS_PER_CYCLE);
    const key = `${rowIdx}:${BANDS.indexOf(obs.band_name)}`;
    this._matrixData[key] = obs;
    this._renderMatrix();
    // If a new detection just landed, refresh the history view immediately so
    // the user sees the green cell without waiting for the next minute tick.
    if (obs.detected) {
      this._loadHistory();
    }
  }

  // ── Matrix rendering ───────────────────────────────────────────────────────

  _renderMatrix() {
    if (!this._matrixBody) return;
    const rows = [];
    for (let s = 0; s < SLOTS_PER_CYCLE; s++) {
      const b = BEACONS[s];
      const isActiveRow = (this._activeSlot !== null && s === this._activeSlot);
      const rowClass = isActiveRow ? "beacon-row--active" : "";
      let cells = `<td class="beacon-callsign ${isActiveRow ? "fw-bold text-warning" : "text-info"}" title="${b.callsign} — ${b.location}">${b.callsign}<span class="beacon-loc">— ${b.location}</span></td>`;
      for (let bi = 0; bi < BANDS.length; bi++) {
        const isActiveCell = isActiveRow && bi === this._activeBand;
        const key = `${s}:${bi}`;
        const obs = this._matrixData[key];
        cells += this._renderCell(obs, isActiveCell);
      }
      rows.push(`<tr class="${rowClass}">${cells}</tr>`);
    }
    this._matrixBody.innerHTML = rows.join("");
  }

  _renderCell(obs, isActive) {
    let inner = "<span class='text-secondary'>·</span>";
    let cls = "beacon-cell";
    if (isActive) cls += " beacon-cell--active";
    if (obs) {
      if (obs.detected) {
        const dashes = obs.dash_levels_detected || 0;
        const snr = obs.snr_db_100w != null ? obs.snr_db_100w.toFixed(1) : "?";
        const meter = renderBeaconMeter(dashes);
        const confirmedMark = obs.id_confirmed ? '<span class="text-success" title="ID confirmed">✓</span> ' : "";
        inner = `<small>${confirmedMark}${meter} ${snr} dB</small>`;
        cls += obs.id_confirmed ? " beacon-cell--confirmed" : " beacon-cell--detected";
      } else {
        inner = `<span class="text-danger" style="font-size:1.1rem">●</span>`;
        cls += " beacon-cell--absent";
      }
    } else if (isActive) {
      inner = "<span class='beacon-cell__spinner'>⏳</span>";
    }
    return `<td class="${cls} text-center">${inner}</td>`;
  }

  // ── Countdown ──────────────────────────────────────────────────────────────

  _startCountdown(slotStartIso) {
    clearInterval(this._countdownTimer);
    if (!this._countdown) return;
    const startMs = new Date(slotStartIso).getTime();
    const endMs = startMs + SLOT_SECONDS * 1000;
    const tick = () => {
      const remaining = Math.max(0, (endMs - Date.now()) / 1000);
      this._countdown.textContent = `Next slot in ${remaining.toFixed(1)} s`;
      if (remaining <= 0) clearInterval(this._countdownTimer);
    };
    tick();
    this._countdownTimer = setInterval(tick, 100);
  }

  // ── Status badge ───────────────────────────────────────────────────────────

  _refreshStatusBadge() {
    if (!this._statusBadge) return;
    if (this._schedulerRunning) {
      this._statusBadge.textContent = "● Running";
      this._statusBadge.className = "btn btn-sm btn-success";
    } else {
      this._statusBadge.textContent = "○ Stopped";
      this._statusBadge.className = "btn btn-sm btn-secondary";
    }
    this._statusBadge.disabled = true;
    if (this._startBtn) {
      this._startBtn.disabled = this._schedulerRunning;
      // Restore the original label once the scheduler is running (or stopped),
      // overriding the "Starting… Please wait" optimistic text.
      this._startBtn.innerHTML = "&#x25B6; Start monitoring";
    }
    if (this._stopBtn)  this._stopBtn.disabled  = !this._schedulerRunning;
  }

  // ── Public API: start/stop + getters ──────────────────────────────────────

  async start() {
    this._beaconModeActive = true;

    // Disable band & mode buttons (scheduler owns the scan engine)
    this._bandBtns.forEach(b => { b.disabled = true; });
    this._modeBtns.forEach(b => { b.disabled = true; });
    this._extraScanBtns.forEach(b => { b.disabled = true; });

    // Style the beacon mode button
    if (this._beaconModeBtn) {
      this._beaconModeBtn.classList.add("is-active");
      this._beaconModeBtn.setAttribute("aria-pressed", "true");
    }

    // Render the empty 18×5 matrix immediately so the user sees the
    // beacon list (callsigns + waiting markers) before scheduler starts.
    this._renderMatrix();
    // NOTE: do NOT auto-start the scheduler here. The user must click
    // "Start monitoring" inside the panel to begin scanning.
  }

  async stop() {
    this._beaconModeActive = false;
    this._currentFreqHz = null;
    this._currentCallsign = null;

    // Release the VFO display lock (set by _syncBeaconContext on slot_start)
    if (typeof window._syncBeaconContext === "function") {
      try { window._syncBeaconContext(); } catch (_) {}
    }

    // Re-enable band & mode buttons
    this._bandBtns.forEach(b => { b.disabled = false; });
    this._modeBtns.forEach(b => { b.disabled = false; });
    this._extraScanBtns.forEach(b => { b.disabled = false; });

    // Deactivate beacon mode button
    if (this._beaconModeBtn) {
      this._beaconModeBtn.classList.remove("is-active");
      this._beaconModeBtn.setAttribute("aria-pressed", "false");
    }

    // If scheduler is running when leaving the mode, stop it for safety.
    // (Otherwise we'd keep parking the SDR with no UI to show it.)
    if (this._schedulerRunning) {
      try {
        await fetch("/api/beacons/stop", {
          method: "POST",
          headers: this._authHeaders(),
        });
      } catch (_) {}
    }
  }

  isBeaconModeActive() {
    return this._beaconModeActive;
  }

  get currentFreqHz() {
    return this._currentFreqHz;
  }

  get currentCallsign() {
    return this._currentCallsign;
  }

  // ── UI bindings ────────────────────────────────────────────────────────────

  _bindUI() {
    // History controls
    this._historyHours?.addEventListener("change", () => this._loadHistory());
    this._historyRefresh?.addEventListener("click", () => this._loadHistory());

    // Start/stop buttons inside the inline panel
    this._startBtn?.addEventListener("click", async () => {
      // Optimistic UI: give immediate feedback while the backend aligns to
      // the next UTC 10-second boundary and warms up the SDR (can take up
      // to ~10 s before the first slot_start arrives).
      if (this._startBtn) {
        this._startBtn.disabled = true;
        this._startBtn.textContent = "Starting\u2026 Please wait";
      }
      if (this._statusBadge) {
        this._statusBadge.textContent = "\u23F3 Starting\u2026";
        this._statusBadge.className = "btn btn-sm btn-warning";
      }
      if (this._countdown) {
        this._countdown.textContent = "Aligning to next UTC slot\u2026";
      }
      try {
        await fetch("/api/beacons/start", {
          method: "POST",
          headers: this._authHeaders(),
        });
      } catch (_) {}
    });
    this._stopBtn?.addEventListener("click", async () => {
      // Optimistic UI: update state immediately so the user sees feedback,
      // even if the backend takes a moment to finalize the in-flight slot.
      this._schedulerRunning = false;
      this._activeSlot = null;
      this._activeBand = null;
      clearInterval(this._countdownTimer);
      if (this._countdown) this._countdown.textContent = "Stopping\u2026";
      this._refreshStatusBadge();
      this._renderMatrix();
      try {
        await fetch("/api/beacons/stop", {
          method: "POST",
          headers: this._authHeaders(),
        });
      } catch (_) {}
      if (this._countdown) this._countdown.textContent = "";
    });
  }

  _authHeaders() {
    // Reuse app.js helper if available globally
    return (typeof getAuthHeader === "function") ? getAuthHeader() : {};
  }
}

/** Render a 4-segment signal-strength meter (light → dark green). */
function renderBeaconMeter(dashes) {
  const n = Math.max(0, Math.min(4, Math.round(dashes || 0)));
  let html = '<span class="beacon-meter" aria-label="signal level ' + n + '/4">';
  for (let i = 1; i <= 4; i++) {
    const cls = i <= n ? `beacon-meter__seg beacon-meter__seg--on-${i}` : "beacon-meter__seg";
    html += `<span class="${cls}"></span>`;
  }
  html += "</span>";
  return html;
}

export { BeaconController, renderBeaconMeter };
