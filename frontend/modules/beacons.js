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
const CYCLE_MS = SLOT_SECONDS * SLOTS_PER_CYCLE * 1000;
const HISTORY_WINDOW_HOURS = 12;
const HISTORY_MODAL_LIMIT = 24;

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
    this._startValidationInFlight = false;
    this._currentFreqHz = null;      // current slot frequency for VFO label
    this._currentCallsign = null;    // current slot beacon callsign
    this._cycleStartMs = null;       // latest 3-minute UTC cycle boundary seen on the wire

    this._matrixBody = document.getElementById("beaconMatrixBody");
    this._statusBadge = document.getElementById("beaconStatusBadge");
    this._countdown   = document.getElementById("beaconCountdown");
    this._startBtn    = document.getElementById("beaconStartBtn");
    this._stopBtn     = document.getElementById("beaconStopBtn");
    this._timeSyncModalEl = document.getElementById("beaconTimeSyncModal");
    this._timeSyncModalMessage = document.getElementById("beaconTimeSyncModalMessage");
    this._timeSyncModalReason = document.getElementById("beaconTimeSyncModalReason");
    this._timeSyncModalSource = document.getElementById("beaconTimeSyncModalSource");
    this._timeSyncModalServer = document.getElementById("beaconTimeSyncModalServer");
    this._timeSyncModalMetrics = document.getElementById("beaconTimeSyncModalMetrics");
    this._timeSyncModalChecks = document.getElementById("beaconTimeSyncModalChecks");
    this._timeSyncModalResolveNote = document.getElementById("beaconTimeSyncModalResolveNote");
    this._timeSyncModalResolveCommands = document.getElementById("beaconTimeSyncModalResolveCommands");
    this._timeSyncModalRetryNote = document.getElementById("beaconTimeSyncModalRetryNote");
    this._historyInfoModalEl = document.getElementById("beaconHistoryInfoModal");
    this._historyInfoWindow = document.getElementById("beaconHistoryInfoWindow");
    this._historyInfoSummary = document.getElementById("beaconHistoryInfoSummary");
    this._historyInfoStats = document.getElementById("beaconHistoryInfoStats");
    this._historyInfoMixChart = document.getElementById("beaconHistoryInfoMixChart");
    this._historyInfoDetectionChart = document.getElementById("beaconHistoryInfoDetectionChart");
    this._historyInfoSnrChart = document.getElementById("beaconHistoryInfoSnrChart");
    this._historyInfoDashChart = document.getElementById("beaconHistoryInfoDashChart");
    this._historyInfoRecords = document.getElementById("beaconHistoryInfoRecords");
    this._historyBody    = document.getElementById("beaconHistoryBody");
    this._historyRefresh = document.getElementById("beaconHistoryRefresh");
    this._historyTimer   = null;
    this._historyCells   = new Map();
    this._historyLoadSeq = 0;
    this._historyInfoSeq = 0;
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

  // ── Initial matrix load (restore whatever the backend can still provide) ───

  async _loadInitialMatrix() {
    try {
      const r = await fetch("/api/beacons/matrix", { cache: "no-store" });
      if (!r.ok) return;
      const data = await r.json();
      this._setCycleStartFromIso(data?.cycle_start_utc);
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

  _cycleStartMsFor(slotStartIso) {
    const slotStartMs = Date.parse(slotStartIso);
    if (Number.isNaN(slotStartMs)) return null;
    return slotStartMs - (slotStartMs % CYCLE_MS);
  }

  _setCycleStartFromIso(slotStartIso) {
    const cycleStartMs = this._cycleStartMsFor(slotStartIso);
    if (cycleStartMs != null) {
      this._cycleStartMs = cycleStartMs;
    }
  }

  _formatMetricMs(value) {
    const num = Number(value);
    if (!Number.isFinite(num)) return null;
    if (Math.abs(num) < 1.0) return `${num.toFixed(3)} ms`;
    return `${num.toFixed(1)} ms`;
  }

  _formatTimeSyncReason(code) {
    const map = {
      ok: "Host UTC time validated",
      not_synchronized: "System clock is not synchronized",
      ntp_inactive: "NTP service is not active",
      no_active_server: "No active NTP server detected",
      offset_too_high: "Clock offset too high",
      root_distance_too_high: "Time source distance too high",
      leap_not_normal: "Non-normal leap state reported",
      probe_partial: "Time sync probe incomplete",
      probe_unavailable: "Time sync probe unavailable",
    };
    return map[String(code || "").trim()] || "Time sync validation failed";
  }

  _buildTimeSyncRecipe(timeSync) {
    const sync = timeSync && typeof timeSync === "object" ? timeSync : {};
    const source = String(sync.source || "").trim().toLowerCase();
    const ntpService = String(sync.ntp_service || "").trim().toLowerCase();
    const reasonCode = String(sync.reason_code || "").trim().toLowerCase();
    const isTimedatectl = source === "timedatectl" || ["active", "inactive", "failed", "disabled", "no"].includes(ntpService);
    const isChrony = source === "chrony";
    const verifyCommands = isChrony
      ? [
          "chronyc tracking",
          "chronyc sources -v",
          "timedatectl status",
        ]
      : isTimedatectl
        ? [
            "timedatectl status",
            "timedatectl timesync-status",
          ]
        : [
            "timedatectl status",
            "timedatectl timesync-status",
            "chronyc tracking",
            "chronyc sources -v",
          ];

    if (isChrony) {
      return {
        verifyCommands,
        resolveNote: reasonCode === "offset_too_high" || reasonCode === "root_distance_too_high"
          ? "Chrony is present but the clock quality is still outside the safe Beacon thresholds. Force an immediate step, then verify again."
          : "Chrony is the active time source on this host. Re-enable it if needed, then verify again.",
        resolveCommands: [
          "sudo systemctl enable --now chrony",
          "sudo chronyc makestep",
          "chronyc tracking",
          "chronyc sources -v",
        ],
        retryNote: "Retry Beacon Analysis only after chrony reports a synchronized clock and at least one valid source.",
      };
    }

    if (isTimedatectl) {
      return {
        verifyCommands,
        resolveNote: reasonCode === "ntp_inactive"
          ? "The host reports systemd time sync but NTP is inactive. Re-enable it, restart the service, then verify again."
          : "The host reports systemd time sync. Re-enable NTP, restart the service, wait a few seconds, then verify again.",
        resolveCommands: [
          "sudo timedatectl set-ntp true",
          "sudo systemctl restart systemd-timesyncd",
          "timedatectl status",
          "timedatectl timesync-status",
        ],
        retryNote: "Retry Beacon Analysis only after timedatectl reports 'System clock synchronized: yes' and a valid server.",
      };
    }

    return {
      verifyCommands,
      resolveNote: "4ham could not identify the active time-sync stack on this host. Use the commands below for the stack that is installed, then verify again before retrying Beacon Analysis.",
      resolveCommands: [
        "# systemd-timesyncd",
        "sudo timedatectl set-ntp true",
        "sudo systemctl restart systemd-timesyncd",
        "",
        "# chrony",
        "sudo systemctl enable --now chrony",
        "sudo chronyc makestep",
      ],
      retryNote: "Retry Beacon Analysis only after one of the verification paths reports a synchronized clock and an active source.",
    };
  }

  _renderTimeSyncModal(timeSync, message) {
    if (!this._timeSyncModalEl) return;
    const sync = timeSync && typeof timeSync === "object" ? timeSync : {};
    const recipe = this._buildTimeSyncRecipe(sync);
    const serverBits = [];
    if (sync.server_name) serverBits.push(sync.server_name);
    if (sync.server_address) serverBits.push(sync.server_address);
    const metrics = [];
    const offset = this._formatMetricMs(sync.offset_ms);
    const jitter = this._formatMetricMs(sync.jitter_ms);
    const rootDistance = this._formatMetricMs(sync.root_distance_ms);
    if (offset) metrics.push(`offset ${offset}`);
    if (jitter) metrics.push(`jitter ${jitter}`);
    if (rootDistance) metrics.push(`root distance ${rootDistance}`);
    if (this._timeSyncModalMessage) {
      this._timeSyncModalMessage.textContent =
        message || sync.message || "Beacon Analysis start was blocked because 4ham could not validate the host UTC time with enough confidence.";
    }
    if (this._timeSyncModalReason) {
      this._timeSyncModalReason.textContent = this._formatTimeSyncReason(sync.reason_code);
    }
    if (this._timeSyncModalSource) {
      this._timeSyncModalSource.textContent = sync.source || "unknown";
    }
    if (this._timeSyncModalServer) {
      this._timeSyncModalServer.textContent = serverBits.join(" | ") || "No active server reported";
    }
    if (this._timeSyncModalMetrics) {
      const leap = sync.leap_status ? `leap ${sync.leap_status}` : null;
      this._timeSyncModalMetrics.textContent = [...metrics, leap].filter(Boolean).join(" | ") || "No detailed metrics reported";
    }
    if (this._timeSyncModalChecks) {
      this._timeSyncModalChecks.textContent = recipe.verifyCommands.join("\n");
    }
    if (this._timeSyncModalResolveNote) {
      this._timeSyncModalResolveNote.textContent = recipe.resolveNote;
    }
    if (this._timeSyncModalResolveCommands) {
      this._timeSyncModalResolveCommands.textContent = recipe.resolveCommands.join("\n");
    }
    if (this._timeSyncModalRetryNote) {
      this._timeSyncModalRetryNote.textContent = recipe.retryNote;
    }
  }

  _showTimeSyncModal(timeSync, message) {
    this._renderTimeSyncModal(timeSync, message);
    if (this._timeSyncModalEl && window.bootstrap?.Modal) {
      window.bootstrap.Modal.getOrCreateInstance(this._timeSyncModalEl).show();
    }
  }

  _setStartValidationUi() {
    if (this._startBtn) {
      this._startBtn.disabled = true;
      this._startBtn.textContent = "Validating UTC time\u2026";
    }
    if (this._statusBadge) {
      this._statusBadge.textContent = "\u23F3 Checking UTC\u2026";
      this._statusBadge.className = "btn btn-sm btn-warning";
    }
    if (this._countdown) {
      this._countdown.textContent = "Checking host UTC time\u2026";
    }
    if (this._stopBtn) {
      this._stopBtn.disabled = true;
    }
  }

  _restoreStoppedUi() {
    this._startValidationInFlight = false;
    this._schedulerRunning = false;
    clearInterval(this._countdownTimer);
    if (this._countdown) this._countdown.textContent = "";
    this._refreshStatusBadge();
  }

  _resetLiveMatrix() {
    this._matrixData = {};
    this._activeSlot = null;
    this._activeBand = null;
    this._cycleStartMs = null;
  }

  // ── Recent activity heatmap (last N hours) ─────────────────────────────────

  async _loadHistory() {
    if (!this._historyBody) return;
    const hours = HISTORY_WINDOW_HOURS;
    const requestSeq = ++this._historyLoadSeq;
    try {
      const r = await fetch(`/api/beacons/heatmap?hours=${encodeURIComponent(hours)}`, { cache: "no-store" });
      if (!r.ok) return;
      const data = await r.json();
      if (requestSeq !== this._historyLoadSeq) return;
      this._renderHistory(data?.matrix, hours);
    } catch (_) {}
  }

  _renderHistory(matrix, hours) {
    if (!this._historyBody || !Array.isArray(matrix)) return;
    this._historyCells.clear();
    const rows = [];
    for (let s = 0; s < SLOTS_PER_CYCLE; s++) {
      const b = BEACONS[s];
      let cells = `<td class="beacon-callsign text-info" title="${b.callsign} — ${b.location}">${b.callsign}<span class="beacon-loc">— ${b.location}</span></td>`;
      const row = matrix[s] || [];
      for (let bi = 0; bi < BANDS.length; bi++) {
        cells += this._renderHistoryCell(row[bi], s, bi, hours);
      }
      rows.push(`<tr>${cells}</tr>`);
    }
    if (!rows.length) {
      this._historyBody.innerHTML = `<tr><td colspan="6" class="text-center text-muted small py-3">No data in last ${formatHistoryWindow(hours)}</td></tr>`;
      return;
    }
    this._historyBody.innerHTML = rows.join("");
  }

  _renderHistoryCell(cell, slotIndex, bandIndex, hours) {
    const detail = {
      callsign: BEACONS[slotIndex]?.callsign || "?",
      location: BEACONS[slotIndex]?.location || "Unknown location",
      band: BANDS[bandIndex] || "?",
      hours,
      cell: cell || null,
    };
    const detailKey = `${slotIndex}:${bandIndex}:${hours}`;
    this._historyCells.set(detailKey, detail);
    const infoButton = renderHistoryInfoButton(detailKey, detail);
    if (!cell || !cell.total_slots) {
      return `<td class="beacon-cell beacon-cell--history-unsampled text-secondary text-center"><small class="beacon-history-cell"><span class="beacon-history-cell__body"><span title="No monitored slots in window">·</span></span>${infoButton}</small></td>`;
    }
    const det   = Number(cell.detections || 0);
    const total = Number(cell.total_slots || 0);
    if (det <= 0) {
      const title = `Monitored ${total} slot(s) in window\n0 detected passes\nHistorical summary counts detected passes only; weak live telemetry below threshold is excluded.`;
      return `<td class="beacon-cell beacon-cell--history-monitored text-center" title="${title}">
        <small class="beacon-history-cell text-white">
          <span class="beacon-history-cell__body">
            <span class="beacon-meter-row">
              ${renderBeaconMeter(0, "nocopy")}
              <span class="beacon-meter-value">0</span>
            </span>
            <span class="beacon-history-meta">0/${total} mon</span>
          </span>
          ${infoButton}
        </small>
      </td>`;
    }
    const bestDashes = Math.max(0, Math.min(4, Math.round(Number(cell.best_dashes || 0))));
    const bestSnr = Number.isFinite(Number(cell.best_snr_db)) ? Number(cell.best_snr_db).toFixed(1) : "n/a";
    const bestPass = {
      dash_levels_detected: bestDashes,
      snr_db_100w: cell.best_snr_db,
    };
    const title = [
      `Detected ${det}/${total} monitored slots in window`,
      `Best detected pass: 100 W ${bestSnr} dB, sequence ${bestDashes}/4, at ${cell.best_detected_utc || "?"}`,
      `Latest detected pass: ${cell.latest_detected_utc || "?"}`,
      "Historical summary counts detected passes only; weak live telemetry below threshold is excluded.",
    ].join("\n");
    const summary = `${det}/${total} mon`;
    return `<td class="beacon-cell beacon-cell--history-hit text-center" title="${title}">
      <small class="beacon-history-cell text-white">
        <span class="beacon-history-cell__body">
          ${renderBeaconTelemetry(bestPass)}
          <span class="beacon-history-meta">${summary}</span>
        </span>
        ${infoButton}
      </small>
    </td>`;
  }

  _renderHistoryInfoModal(detail) {
    if (this._historyInfoWindow) {
      this._historyInfoWindow.textContent = `${detail.callsign} — ${detail.location} · ${detail.band} · rolling ${formatHistoryWindow(detail.hours)}`;
    }
    if (!this._historyInfoSummary) {
      return;
    }
    const cell = detail.cell;
    if (!cell || !cell.total_slots) {
      this._historyInfoSummary.textContent = "No monitored slots were recorded for this beacon/band cell in the rolling history window.";
      return;
    }
    const total = Number(cell.total_slots || 0);
    const detections = Number(cell.detections || 0);
    const noCopy = Math.max(total - detections, 0);
    const bestSnr = Number.isFinite(Number(cell.best_snr_db)) ? `${Number(cell.best_snr_db).toFixed(1)} dB` : "n/a";
    const bestSeq = Math.max(0, Math.min(4, Math.round(Number(cell.best_dashes || 0))));
    const latest = formatUtcTimestamp(cell.latest_detected_utc);
    if (detections <= 0) {
      this._historyInfoSummary.textContent = `Monitored ${total} slot(s) in the rolling 12-hour window. No detected passes were recorded for this cell.`;
      this._renderHistoryInfoVisuals(detail, []);
      return;
    }
    this._historyInfoSummary.textContent = `Detected ${detections}/${total} monitored slot(s). No copy: ${noCopy}. Best detected pass: ${bestSnr}, sequence ${bestSeq}/4. Latest detected pass: ${latest}.`;
    this._renderHistoryInfoVisuals(detail, []);
  }

  _renderHistoryInfoVisuals(detail, observations) {
    const cell = detail.cell || {};
    if (this._historyInfoStats) {
      this._historyInfoStats.innerHTML = renderHistoryInfoStats(detail, observations);
    }
    if (this._historyInfoMixChart) {
      this._historyInfoMixChart.innerHTML = renderHistoryMixChart(cell);
    }
    if (this._historyInfoDetectionChart) {
      this._historyInfoDetectionChart.innerHTML = renderHistoryRhythmChart(observations);
    }
    if (this._historyInfoSnrChart) {
      this._historyInfoSnrChart.innerHTML = renderHistoryMetricChart(observations, "snr");
    }
    if (this._historyInfoDashChart) {
      this._historyInfoDashChart.innerHTML = renderHistoryMetricChart(observations, "dash");
    }
  }

  async _openHistoryInfo(detailKey) {
    const detail = this._historyCells.get(detailKey);
    if (!detail) {
      return;
    }
    this._renderHistoryInfoModal(detail);
    if (this._historyInfoRecords) {
      this._historyInfoRecords.innerHTML = '<div class="text-muted">Loading details…</div>';
    }
    if (this._historyInfoModalEl && window.bootstrap?.Modal) {
      window.bootstrap.Modal.getOrCreateInstance(this._historyInfoModalEl).show();
    }
    if (!detail.cell?.total_slots) {
      if (this._historyInfoRecords) {
        this._historyInfoRecords.innerHTML = '<div class="text-muted">No observation rows exist for this cell in the rolling history window.</div>';
      }
      return;
    }

    const requestSeq = ++this._historyInfoSeq;
    const params = new URLSearchParams({
      callsign: detail.callsign,
      band: detail.band,
      hours: String(detail.hours),
      limit: String(HISTORY_MODAL_LIMIT),
    });
    try {
      const response = await fetch(`/api/beacons/observations?${params.toString()}`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error("history_detail_fetch_failed");
      }
      const payload = await response.json();
      if (requestSeq !== this._historyInfoSeq) {
        return;
      }
      const observations = Array.isArray(payload?.observations) ? payload.observations : [];
      this._renderHistoryInfoVisuals(detail, observations);
      this._renderHistoryInfoRows(observations);
    } catch (_) {
      if (requestSeq !== this._historyInfoSeq) {
        return;
      }
      if (this._historyInfoRecords) {
        this._historyInfoRecords.innerHTML = '<div class="text-danger">Unable to load observation details for this cell.</div>';
      }
    }
  }

  _renderHistoryInfoRows(observations) {
    if (!this._historyInfoRecords) {
      return;
    }
    if (!observations.length) {
      this._historyInfoRecords.innerHTML = '<div class="text-muted">No observation rows matched this cell in the rolling 12-hour window.</div>';
      return;
    }
    const rows = observations.map((obs) => {
      return `<tr>
        <td>${escapeHtml(formatUtcTimestamp(obs.slot_start_utc))}</td>
        <td>${renderHistoryStateBadge(obs)}</td>
        <td>${renderHistoryRowMetric(obs, "snr")}</td>
        <td>${renderHistoryRowMetric(obs, "dash")}</td>
      </tr>`;
    });
    this._historyInfoRecords.innerHTML = `<div class="table-responsive beacon-history-info-table-wrap">
      <table class="table table-sm table-dark align-middle mb-0 beacon-history-info-table">
        <thead>
          <tr>
            <th>UTC slot</th>
            <th>Observation</th>
            <th>100 W profile</th>
            <th>Sequence profile</th>
          </tr>
        </thead>
        <tbody>${rows.join("")}</tbody>
      </table>
    </div>`;
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
    const nextCycleStartMs = this._cycleStartMsFor(msg.slot_start_utc);

    // Keep the last monitored pass visible across the monitoring session.
    // If the previous active cell never received an observation event, close
    // it as a no-copy pass instead of letting it stay blank indefinitely.
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
    if (nextCycleStartMs != null) {
      this._cycleStartMs = nextCycleStartMs;
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
    const obsCycleStartMs = this._cycleStartMsFor(obs.slot_start_utc);
    if (obsCycleStartMs != null) {
      if (this._cycleStartMs == null) {
        this._cycleStartMs = obsCycleStartMs;
      } else if (obsCycleStartMs !== this._cycleStartMs) {
        return;
      }
    }
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
        const title = renderBeaconCellTitle(obs);
        inner = `<small class="beacon-cell__reading" title="${title}">${renderBeaconTelemetry(obs)}</small>`;
        cls += " beacon-cell--detected";
      } else {
        inner = `<span title="Latest monitored pass: no copy">${renderBeaconMeter(0, "nocopy")}</span>`;
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
    if (this._startValidationInFlight && !this._schedulerRunning) {
      this._setStartValidationUi();
      this._statusBadge.disabled = true;
      if (typeof window.refreshModeButtons === "function") {
        try { window.refreshModeButtons(); } catch (_) {}
      }
      return;
    }
    if (this._schedulerRunning) {
      this._statusBadge.textContent = "● Running";
      this._statusBadge.className = "btn btn-sm btn-success";
    } else {
      this._statusBadge.textContent = "○ Stopped";
      this._statusBadge.className = "btn btn-sm btn-secondary";
    }
    this._statusBadge.disabled = true;
    if (typeof window.refreshModeButtons === "function") {
      try { window.refreshModeButtons(); } catch (_) {}
    }
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

    if (!this._schedulerRunning) {
      this._resetLiveMatrix();
    }

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

  isSchedulerRunning() {
    return this._schedulerRunning;
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
    this._historyRefresh?.addEventListener("click", () => this._loadHistory());
    this._historyBody?.addEventListener("click", (event) => {
      const trigger = event.target.closest("[data-beacon-history-info]");
      if (!trigger) {
        return;
      }
      event.preventDefault();
      this._openHistoryInfo(trigger.getAttribute("data-beacon-history-info"));
    });

    // Start/stop buttons inside the inline panel
    this._startBtn?.addEventListener("click", async () => {
      if (this._startValidationInFlight || this._schedulerRunning) {
        return;
      }
      this._startValidationInFlight = true;
      this._setStartValidationUi();
      try {
        const response = await fetch("/api/beacons/start", {
          method: "POST",
          headers: this._authHeaders(),
        });
        if (!response.ok) {
          let payload = null;
          try {
            payload = await response.json();
          } catch (_) {}
          const detail = payload?.detail;
          if (response.status === 412 && detail?.code === "beacon_time_sync_unhealthy") {
            this._restoreStoppedUi();
            this._showTimeSyncModal(detail.time_sync || {}, detail.message || "Beacon Analysis start is blocked until host UTC time is healthy.");
            return;
          }
          this._restoreStoppedUi();
          return;
        }

        this._startValidationInFlight = false;
        this._resetLiveMatrix();
        this._renderMatrix();

        // Optimistic UI only after the backend accepted the start request.
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
      } catch (_) {
        this._restoreStoppedUi();
      }
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

function referenceMeterLevel(snrDb) {
  const value = Number(snrDb);
  if (!Number.isFinite(value) || value < 0.0) return 0;
  if (value < 1.5) return 1;
  if (value < 3.0) return 2;
  if (value < 4.5) return 3;
  return 4;
}

function renderBeaconTelemetry(obs) {
  const dashCount = Math.max(0, Math.min(4, Math.round(Number(obs.dash_levels_detected || 0))));
  const snrLabel = Number.isFinite(Number(obs.snr_db_100w)) ? `${Number(obs.snr_db_100w).toFixed(1)} dB` : "n/a";
  return `<span class="beacon-cell__telemetry">
    <span class="beacon-meter-row" title="100 W reference dash: ${snrLabel}">
      ${renderBeaconMeter(referenceMeterLevel(obs.snr_db_100w))}
      <span class="beacon-meter-value">${snrLabel}</span>
    </span>
    <span class="beacon-meter-row" title="Ordered dash sequence heard: ${dashCount}/4">
      ${renderBeaconMeter(dashCount)}
      <span class="beacon-meter-value">${dashCount}/4</span>
    </span>
  </span>`;
}

function renderBeaconCellTitle(obs) {
  const dashCount = Math.max(0, Math.min(4, Math.round(Number(obs.dash_levels_detected || 0))));
  const snrLabel = Number.isFinite(Number(obs.snr_db_100w)) ? `${Number(obs.snr_db_100w).toFixed(1)} dB` : "n/a";
  return [
    `100 W reference dash: ${snrLabel}`,
    `Ordered dash sequence heard: ${dashCount}/4`,
  ].join("\n");
}

function renderHistoryInfoButton(detailKey, detail) {
  return `<button type="button" class="beacon-history-info-btn" data-beacon-history-info="${escapeHtml(detailKey)}" title="Events for ${escapeHtml(detail.callsign)} ${escapeHtml(detail.band)}" aria-label="Events for ${escapeHtml(detail.callsign)} on ${escapeHtml(detail.band)}">Events</button>`;
}

function renderHistoryInfoStats(detail, observations) {
  const cell = detail.cell || {};
  const total = Number(cell.total_slots || 0);
  const detections = Number(cell.detections || 0);
  const noCopy = Math.max(total - detections, 0);
  const detectionRate = total > 0 ? `${Math.round((detections / total) * 100)}%` : "0%";
  const noCopyRate = total > 0 ? `${Math.round((noCopy / total) * 100)}%` : "0%";
  const bestSnr = Number.isFinite(Number(cell.best_snr_db)) ? `${Number(cell.best_snr_db).toFixed(1)} dB` : "n/a";
  const bestSeq = `${Math.max(0, Math.min(4, Math.round(Number(cell.best_dashes || 0))))}/4`;
  const latest = formatUtcTimestamp(cell.latest_detected_utc);
  const cards = [
    { label: "Window", value: formatHistoryWindow(detail.hours), note: "Fixed rolling view" },
    { label: "Coverage", value: `${total} slot(s)`, note: "Monitored in rolling view" },
    { label: "Detected", value: `${detections} slot(s)`, note: `${detectionRate} of monitored coverage` },
    { label: "No copy", value: `${noCopy} slot(s)`, note: `${noCopyRate} of monitored coverage` },
    { label: "Best pass", value: `${bestSnr} · ${bestSeq}`, note: formatUtcTimestamp(cell.best_detected_utc) },
    { label: "Latest detected", value: latest, note: `${observations.length} latest monitored rows loaded` },
  ];
  return cards.map((card) => `
    <div class="beacon-history-info-stat">
      <div class="beacon-history-info-stat__label">${escapeHtml(card.label)}</div>
      <div class="beacon-history-info-stat__value">${escapeHtml(card.value)}</div>
      <div class="beacon-history-info-stat__note">${escapeHtml(card.note)}</div>
    </div>
  `).join("");
}

function renderHistoryMixChart(cell) {
  const total = Number(cell.total_slots || 0);
  if (total <= 0) {
    return '<div class="beacon-history-chart__empty">No monitored slots in the rolling 12-hour window.</div>';
  }
  const detections = Math.max(0, Number(cell.detections || 0));
  const noCopy = Math.max(total - detections, 0);
  return `<div class="beacon-history-mix">
    <div class="beacon-history-mix__bar" role="img" aria-label="Copy mix across the rolling 12-hour window">
      <span class="beacon-history-mix__seg beacon-history-mix__seg--observed" style="width:${pct(detections, total)}%"></span>
      <span class="beacon-history-mix__seg beacon-history-mix__seg--nocopy" style="width:${pct(noCopy, total)}%"></span>
    </div>
    <div class="beacon-history-mix__legend">
      ${renderMixLegendItem("Detected", detections, total, "observed")}
      ${renderMixLegendItem("No copy", noCopy, total, "nocopy")}
    </div>
  </div>`;
}

function renderHistoryRhythmChart(observations) {
  if (!observations.length) {
    return '<div class="beacon-history-chart__empty">Load a monitored cell to see the latest copy rhythm.</div>';
  }
  const detected = observations.filter((obs) => obs.detected).length;
  const noCopy = observations.length - detected;
  const detectionRate = observations.length > 0 ? `${Math.round((detected / observations.length) * 100)}%` : "0%";
  const bars = observations.slice().reverse().map((obs) => {
    const cls = obs.detected ? "detected" : "nocopy";
    const height = obs.detected ? 82 : 26;
    const title = `${formatUtcTimestamp(obs.slot_start_utc)} | ${obs.detected ? "Detected slot" : "No copy"}`;
    return `<span class="beacon-history-rhythm__bar beacon-history-rhythm__bar--${cls}" style="height:${height}%" title="${escapeHtml(title)}"></span>`;
  }).join("");
  return `<div class="beacon-history-rhythm">
    <div class="beacon-history-chart__stats">
      ${renderHistoryChartStat("Rows", `${observations.length}`)}
      ${renderHistoryChartStat("Detected", `${detected}`)}
      ${renderHistoryChartStat("No copy", `${noCopy}`)}
      ${renderHistoryChartStat("Detection rate", detectionRate)}
    </div>
    <div class="beacon-history-rhythm__bars">${bars}</div>
    <div class="beacon-history-chart__caption">Older on the left, newer on the right. Blue = detected slot, amber = monitored with no copy.</div>
  </div>`;
}

function renderHistoryMetricChart(observations, kind) {
  if (!observations.length) {
    return '<div class="beacon-history-chart__empty">No monitored rows loaded yet for this chart.</div>';
  }
  const reversed = observations.slice().reverse();
  const values = reversed.map((obs) => {
    if (kind === "snr") {
      return Number.isFinite(Number(obs.snr_db_100w)) ? Number(obs.snr_db_100w) : null;
    }
    return Math.max(0, Math.min(4, Math.round(Number(obs.dash_levels_detected || 0))));
  }).filter((value) => value !== null);
  const maxValue = kind === "snr"
    ? Math.max(6, ...reversed.map((obs) => Math.max(0, Number(obs.snr_db_100w || 0))))
    : 4;
  const bars = reversed.map((obs) => {
    const rawValue = kind === "snr"
      ? Math.max(0, Number(obs.snr_db_100w || 0))
      : Math.max(0, Math.min(4, Math.round(Number(obs.dash_levels_detected || 0))));
    const pctHeight = maxValue > 0 ? Math.max(8, Math.round((rawValue / maxValue) * 100)) : 8;
    const title = kind === "snr"
      ? `${formatUtcTimestamp(obs.slot_start_utc)} | 100 W reference ${Number.isFinite(Number(obs.snr_db_100w)) ? `${Number(obs.snr_db_100w).toFixed(1)} dB` : "n/a"}`
      : `${formatUtcTimestamp(obs.slot_start_utc)} | Dash copy ${rawValue}/4`;
    const cls = obs.detected ? "live" : "muted";
    return `<span class="beacon-history-metric__bar beacon-history-metric__bar--${cls}" style="height:${pctHeight}%" title="${escapeHtml(title)}"></span>`;
  }).join("");
  const caption = kind === "snr"
    ? "100 W reference-dash intensity across the latest monitored passes."
    : "Ordered dash-copy quality across the same pass history.";
  const latestValue = values.length ? values[values.length - 1] : null;
  const bestValue = values.length ? Math.max(...values) : null;
  const avgValue = values.length ? (values.reduce((sum, value) => sum + value, 0) / values.length) : null;
  return `<div class="beacon-history-metric">
    <div class="beacon-history-chart__stats">
      ${renderHistoryChartStat("Rows", `${observations.length}`)}
      ${renderHistoryChartStat("Latest", formatHistoryMetricValue(latestValue, kind))}
      ${renderHistoryChartStat("Best", formatHistoryMetricValue(bestValue, kind))}
      ${renderHistoryChartStat("Average", formatHistoryMetricValue(avgValue, kind))}
    </div>
    <div class="beacon-history-metric__bars">${bars}</div>
    <div class="beacon-history-chart__caption">${escapeHtml(caption)}</div>
  </div>`;
}

function renderHistoryChartStat(label, value) {
  return `<div class="beacon-history-chart__stat">
    <span class="beacon-history-chart__stat-label">${escapeHtml(label)}</span>
    <strong class="beacon-history-chart__stat-value">${escapeHtml(value)}</strong>
  </div>`;
}

function formatHistoryMetricValue(value, kind) {
  if (!Number.isFinite(Number(value))) {
    return "n/a";
  }
  if (kind === "snr") {
    return `${Number(value).toFixed(1)} dB`;
  }
  return `${Math.max(0, Math.min(4, Math.round(Number(value))))}/4`;
}

function renderHistoryStateBadge(obs) {
  const text = obs.detected ? "Detected" : "No copy";
  const cls = obs.detected ? "detected" : "nocopy";
  return `<span class="beacon-history-state-chip beacon-history-state-chip--${cls}">${escapeHtml(text)}</span>`;
}

function renderHistoryRowMetric(obs, kind) {
  if (kind === "snr") {
    const value = Number(obs.snr_db_100w);
    const width = Number.isFinite(value) ? Math.max(6, Math.min(100, Math.round((Math.max(0, value) / 6) * 100))) : 6;
    const label = Number.isFinite(value) ? `${value.toFixed(1)} dB` : "n/a";
    return `<div class="beacon-history-rowmetric">
      <span class="beacon-history-rowmetric__bar"><span class="beacon-history-rowmetric__fill" style="width:${width}%"></span></span>
      <span class="beacon-history-rowmetric__label">${escapeHtml(label)}</span>
    </div>`;
  }
  const dashes = Math.max(0, Math.min(4, Math.round(Number(obs.dash_levels_detected || 0))));
  return `<div class="beacon-history-rowmetric beacon-history-rowmetric--sequence">
    ${renderBeaconMeter(dashes, dashes > 0 ? "success" : "nocopy")}
    <span class="beacon-history-rowmetric__label">${escapeHtml(`${dashes}/4`)}</span>
  </div>`;
}

function renderMixLegendItem(label, value, total, variant) {
  return `<div class="beacon-history-mix__legend-item">
    <span class="beacon-history-mix__legend-dot beacon-history-mix__legend-dot--${variant}"></span>
    <span>${escapeHtml(label)}</span>
    <strong>${escapeHtml(`${value}`)}</strong>
    <span class="text-muted">${escapeHtml(`${pct(value, total)}%`)}</span>
  </div>`;
}

function pct(value, total) {
  if (!Number.isFinite(Number(total)) || Number(total) <= 0) return 0;
  return Math.round((Number(value) / Number(total)) * 100);
}

function formatHistoryWindow(hours) {
  const value = Number(hours);
  if (!Number.isFinite(value) || value <= 0) return "rolling window";
  if (value < 1) return `${Math.round(value * 60)} min`;
  const wholeHours = Number.isInteger(value) ? String(value) : value.toFixed(1);
  return `${wholeHours} h`;
}

function formatUtcTimestamp(value) {
  if (!value) return "n/a";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toISOString().replace("T", " ").replace(".000Z", " UTC");
}

function formatConfidence(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "n/a";
  return numeric.toFixed(2);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** Render a 4-segment meter for successful copy or no-copy passes. */
function renderBeaconMeter(dashes, variant = "success") {
  const n = Math.max(0, Math.min(4, Math.round(dashes || 0)));
  if (variant === "nocopy" || variant === "fail") {
    let html = '<span class="beacon-meter beacon-meter--nocopy" aria-label="latest monitored pass had no copy">';
    for (let i = 1; i <= 4; i++) {
      html += '<span class="beacon-meter__seg beacon-meter__seg--nocopy"></span>';
    }
    html += "</span>";
    return html;
  }
  let html = '<span class="beacon-meter" aria-label="signal level ' + n + '/4">';
  for (let i = 1; i <= 4; i++) {
    const cls = i <= n ? `beacon-meter__seg beacon-meter__seg--on-${i}` : "beacon-meter__seg";
    html += `<span class="${cls}"></span>`;
  }
  html += "</span>";
  return html;
}

export { BeaconController, renderBeaconMeter };
