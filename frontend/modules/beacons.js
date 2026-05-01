// © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
/**
 * BeaconController — NCDXF/IARU Beacon Analysis frontend module
 *
 * Responsibilities:
 *  - Connect to /ws/beacons
 *  - Render and update the 18×5 beacon matrix modal
 *  - Drive the countdown to the next slot
 *  - Expose enterBeaconMode() / exitBeaconMode() for app.js
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

    this._modal = document.getElementById("beaconModal");
    this._matrixBody = document.getElementById("beaconMatrixBody");
    this._statusBadge = document.getElementById("beaconStatusBadge");
    this._bandBadge   = document.getElementById("beaconBandBadge");
    this._countdown   = document.getElementById("beaconCountdown");
    this._startBtn    = document.getElementById("beaconStartBtn");
    this._stopBtn     = document.getElementById("beaconStopBtn");
    this._viewBtn     = document.getElementById("viewBeaconRotationBtn");
    this._rotBtn      = document.getElementById("rotationToggleBtn");
    this._bandBtns    = Array.from(document.querySelectorAll("[data-quick-band]"));
    this._beaconModeBtn = document.querySelector('[data-quick-mode="BEACON"]');

    this._bindUI();
    this._connect();
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
    this._activeSlot = msg.slot_index;
    this._activeBand = BANDS.indexOf(msg.band_name);
    this._schedulerRunning = true;
    this._refreshStatusBadge();
    this._renderMatrix();
    this._startCountdown(msg.slot_start_utc);
  }

  _onObservation(obs) {
    const key = `${obs.slot_index % SLOTS_PER_CYCLE}:${BANDS.indexOf(obs.band_name)}`;
    this._matrixData[key] = obs;
    this._renderMatrix();
  }

  // ── Matrix rendering ───────────────────────────────────────────────────────

  _renderMatrix() {
    if (!this._matrixBody) return;
    const rows = [];
    for (let s = 0; s < SLOTS_PER_CYCLE; s++) {
      const b = BEACONS[s];
      const isActiveRow = (this._activeSlot !== null && s === (this._activeSlot % SLOTS_PER_CYCLE));
      const rowClass = isActiveRow ? "beacon-row--active" : "";
      let cells = `<td class="beacon-callsign ${isActiveRow ? "fw-bold text-warning" : "text-info"}">${b.callsign}</td>`;
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
    let inner = "·";
    let cls = "beacon-cell";
    if (isActive) cls += " beacon-cell--active";
    if (obs) {
      if (obs.detected) {
        const dashes = obs.dash_levels_detected || 0;
        const snr = obs.snr_db_100w != null ? obs.snr_db_100w.toFixed(1) : "?";
        inner = `<span class="beacon-dashes">${"▐".repeat(dashes)}${"░".repeat(4 - dashes)}</span><br><small>${snr} dB</small>`;
        cls += obs.id_confirmed ? " beacon-cell--confirmed" : " beacon-cell--detected";
      } else {
        inner = "<span class='text-muted'>—</span>";
        cls += " beacon-cell--absent";
      }
    } else if (isActive) {
      inner = "<span class='beacon-cell__spinner'>⏳</span>";
    }
    return `<td class="${cls}">${inner}</td>`;
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
      this._statusBadge.className = "badge bg-success ms-2";
    } else {
      this._statusBadge.textContent = "○ Stopped";
      this._statusBadge.className = "badge bg-secondary ms-2";
    }
    if (this._startBtn) this._startBtn.disabled = this._schedulerRunning;
    if (this._stopBtn)  this._stopBtn.disabled  = !this._schedulerRunning;
  }

  // ── Enter / exit beacon mode ───────────────────────────────────────────────

  async enterBeaconMode() {
    this._beaconModeActive = true;

    // Disable band buttons
    this._bandBtns.forEach(b => { b.disabled = true; });

    // Swap rotation button → view beacon rotation
    if (this._rotBtn) this._rotBtn.classList.add("d-none");
    if (this._viewBtn) this._viewBtn.classList.remove("d-none");

    // Style the beacon mode button
    if (this._beaconModeBtn) {
      this._beaconModeBtn.classList.add("is-active");
      this._beaconModeBtn.setAttribute("aria-pressed", "true");
    }

    // Auto-start scheduler if not running
    if (!this._schedulerRunning) {
      try {
        await fetch("/api/beacons/start", {
          method: "POST",
          headers: this._authHeaders(),
        });
      } catch (_) {}
    }
  }

  async exitBeaconMode() {
    this._beaconModeActive = false;

    // Re-enable band buttons
    this._bandBtns.forEach(b => { b.disabled = false; });

    // Restore rotation button
    if (this._rotBtn) this._rotBtn.classList.remove("d-none");
    if (this._viewBtn) this._viewBtn.classList.add("d-none");

    // Deactivate beacon mode button
    if (this._beaconModeBtn) {
      this._beaconModeBtn.classList.remove("is-active");
      this._beaconModeBtn.setAttribute("aria-pressed", "false");
    }

    // Stop scheduler
    try {
      await fetch("/api/beacons/stop", {
        method: "POST",
        headers: this._authHeaders(),
      });
    } catch (_) {}
  }

  isBeaconModeActive() {
    return this._beaconModeActive;
  }

  // ── UI bindings ────────────────────────────────────────────────────────────

  _bindUI() {
    // Start/stop buttons inside the modal
    this._startBtn?.addEventListener("click", async () => {
      try {
        await fetch("/api/beacons/start", {
          method: "POST",
          headers: this._authHeaders(),
        });
      } catch (_) {}
    });
    this._stopBtn?.addEventListener("click", async () => {
      try {
        await fetch("/api/beacons/stop", {
          method: "POST",
          headers: this._authHeaders(),
        });
      } catch (_) {}
    });

    // Fetch initial matrix when modal opens
    this._modal?.addEventListener("shown.bs.modal", () => {
      this._fetchMatrix();
      this._fetchStatus();
    });
  }

  async _fetchMatrix() {
    try {
      const res = await fetch("/api/beacons/matrix", { headers: this._authHeaders() });
      if (!res.ok) return;
      const data = await res.json();
      // Populate matrixData from history
      (data.matrix || []).forEach((row, slotIdx) => {
        (row || []).forEach((obs, bandIdx) => {
          if (obs) {
            const key = `${slotIdx}:${bandIdx}`;
            this._matrixData[key] = obs;
          }
        });
      });
      this._activeSlot = data.current_slot_index ?? null;
      this._renderMatrix();
    } catch (_) {}
  }

  async _fetchStatus() {
    try {
      const res = await fetch("/api/beacons/status", { headers: this._authHeaders() });
      if (!res.ok) return;
      const data = await res.json();
      this._schedulerRunning = Boolean(data?.scheduler?.running);
      this._refreshStatusBadge();
    } catch (_) {}
  }

  _authHeaders() {
    // Reuse app.js helper if available globally
    return (typeof getAuthHeader === "function") ? getAuthHeader() : {};
  }
}

export { BeaconController };
