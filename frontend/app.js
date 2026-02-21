import { loadPresetsFromJson } from "./utils/presets.js";

const statusEl = document.getElementById("status");
const eventsEl = document.getElementById("events");
const waterfallEl = document.getElementById("waterfall");
const waterfallStatus = document.getElementById("waterfallStatus");
const canvas = document.getElementById("waterfallCanvas");
const ctx = canvas.getContext("2d");
const gainInput = document.getElementById("gain");
const sampleRateInput = document.getElementById("sampleRate");
const recordPathInput = document.getElementById("recordPath");
const logsEl = document.getElementById("logs");
const bandFilter = document.getElementById("bandFilter");
const modeFilter = document.getElementById("modeFilter");
const callsignFilter = document.getElementById("callsignFilter");
const startFilter = document.getElementById("startFilter");
const endFilter = document.getElementById("endFilter");
const exportCsvBtn = document.getElementById("exportCsv");
const pageOffsetLabel = document.getElementById("pageOffset");
const deviceSelect = document.getElementById("deviceSelect");
const bandSelect = document.getElementById("bandSelect");
const authUserInput = document.getElementById("authUser");
const authPassInput = document.getElementById("authPass");
const saveSettingsBtn = document.getElementById("saveSettings");
const refreshDevicesBtn = document.getElementById("refreshDevices");
const bandNameInput = document.getElementById("bandName");
const bandStartInput = document.getElementById("bandStart");
const bandEndInput = document.getElementById("bandEnd");
const saveBandBtn = document.getElementById("saveBand");
const presetNameInput = document.getElementById("presetName");
const savePresetBtn = document.getElementById("savePreset");
const presetSelect = document.getElementById("presetSelect");
const exportPresetsBtn = document.getElementById("exportPresets");
const importPresetsInput = document.getElementById("importPresets");
const favoriteBandsSelect = document.getElementById("favoriteBands");
const addFavoriteBtn = document.getElementById("addFavorite");
const removeFavoriteBtn = document.getElementById("removeFavorite");
const toast = document.getElementById("toast");
const favoriteFilter = document.getElementById("favoriteFilter");
const loginUserInput = document.getElementById("loginUser");
const loginPassInput = document.getElementById("loginPass");
const loginSaveBtn = document.getElementById("loginSave");
const loginStatus = document.getElementById("loginStatus");
const wsStatus = document.getElementById("wsStatus");
const onboarding = document.getElementById("onboarding");
const onboardingTitle = document.getElementById("onboardingTitle");
const onboardingText = document.getElementById("onboardingText");
const onboardingPrev = document.getElementById("onboardingPrev");
const onboardingNext = document.getElementById("onboardingNext");
const startBtn = document.getElementById("startScan");
const stopBtn = document.getElementById("stopScan");
const prevPageBtn = document.getElementById("prevPage");
const nextPageBtn = document.getElementById("nextPage");
const qualityBar = document.getElementById("qualityBar");
const qualityLabel = document.getElementById("qualityLabel");
const bandSummary = document.getElementById("bandSummary");
const modeSummary = document.getElementById("modeSummary");
const pageNumberLabel = document.getElementById("pageNumber");
const showBandSummary = document.getElementById("showBandSummary");
const showModeSummary = document.getElementById("showModeSummary");
const eventsTotal = document.getElementById("eventsTotal");
const totalGlobal = document.getElementById("totalGlobal");
const compactToggle = document.getElementById("compactToggle");
let modeStatsCache = {};
const decoderStatusEl = document.getElementById("decoderStatus");
const wsjtxUdpStatusEl = document.getElementById("wsjtxUdpStatus");
const kissStatusEl = document.getElementById("kissStatus");
const decoderLastEventEl = document.getElementById("decoderLastEvent");
const agcStatusEl = document.getElementById("agcStatus");
const ft8Toggle = document.getElementById("ft8Toggle");
const aprsToggle = document.getElementById("aprsToggle");
const cwToggle = document.getElementById("cwToggle");
const ssbToggle = document.getElementById("ssbToggle");
const saveModesBtn = document.getElementById("saveModes");
let eventOffset = 0;
let row = 0;

function logLine(text) {
  const current = logsEl.textContent === "No logs yet." ? "" : logsEl.textContent;
  logsEl.textContent = `${new Date().toISOString()} ${text}\n${current}`.trim();
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.remove("error");
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2500);
}

function showToastError(message) {
  toast.textContent = message;
  toast.classList.add("error");
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2500);
  logLine(message);
}

function loadPresets() {
  const data = JSON.parse(localStorage.getItem("presets") || "[]");
  presetSelect.innerHTML = "";
  data.forEach((preset) => {
    const option = document.createElement("option");
    option.value = preset.name;
    option.textContent = preset.name;
    option.dataset.payload = JSON.stringify(preset);
    presetSelect.appendChild(option);
  });
}

function persistPresets(text) {
  const parsed = loadPresetsFromJson(text);
  localStorage.setItem("presets", JSON.stringify(parsed));
  loadPresets();
}

function exportPresets() {
  const data = localStorage.getItem("presets") || "[]";
  const blob = new Blob([data], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "presets.json";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  logLine("Presets exported");
  showToast("Presets exported");
}

function savePreset() {
  const data = JSON.parse(localStorage.getItem("presets") || "[]");
  const preset = {
    name: presetNameInput.value || `Preset ${data.length + 1}`,
    band: bandSelect.value,
    gain: Number(gainInput.value),
    sample_rate: Number(sampleRateInput.value),
    record_path: recordPathInput.value || null
  };
  data.push(preset);
  localStorage.setItem("presets", JSON.stringify(data));
  loadPresets();
  logLine("Preset saved");
}

savePresetBtn.addEventListener("click", savePreset);
exportPresetsBtn.addEventListener("click", exportPresets);
importPresetsInput.addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) {
    return;
  }
  const text = await file.text();
  try {
    persistPresets(text);
    showToast("Presets imported");
  } catch (err) {
    showToast("Failed to import presets");
  }
});
presetSelect.addEventListener("change", () => {
  const data = JSON.parse(localStorage.getItem("presets") || "[]");
  const selected = data.find((p) => p.name === presetSelect.value);
  if (!selected) {
    return;
  }
  bandSelect.value = selected.band;
  gainInput.value = selected.gain;
  sampleRateInput.value = selected.sample_rate;
  recordPathInput.value = selected.record_path || "";
  logLine("Preset applied");
});

function loadFavorites() {
  const data = JSON.parse(localStorage.getItem("favoriteBands") || "[]");
  favoriteBandsSelect.innerHTML = "";
  favoriteFilter.innerHTML = "";
  data.forEach((band) => {
    const option = document.createElement("option");
    option.value = band;
    option.textContent = band;
    favoriteBandsSelect.appendChild(option);
    const filterOption = document.createElement("option");
    filterOption.value = band;
    filterOption.textContent = band;
    favoriteFilter.appendChild(filterOption);
  });
}

addFavoriteBtn.addEventListener("click", () => {
  const data = JSON.parse(localStorage.getItem("favoriteBands") || "[]");
  if (!data.includes(bandSelect.value)) {
    data.push(bandSelect.value);
    localStorage.setItem("favoriteBands", JSON.stringify(data));
    loadFavorites();
    logLine("Favorite added");
    syncFavorites();
  }
});

removeFavoriteBtn.addEventListener("click", () => {
  const data = JSON.parse(localStorage.getItem("favoriteBands") || "[]");
  const filtered = data.filter((band) => band !== favoriteBandsSelect.value);
  localStorage.setItem("favoriteBands", JSON.stringify(filtered));
  loadFavorites();
  logLine("Favorite removed");
  syncFavorites();
});

favoriteFilter.addEventListener("change", () => {
  if (favoriteFilter.value) {
    bandFilter.value = favoriteFilter.value;
    fetchEvents();
  }
});

async function syncFavorites() {
  const data = JSON.parse(localStorage.getItem("favoriteBands") || "[]");
  await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeader() },
    body: JSON.stringify({ favorites: data })
  });
}

function getAuthHeader() {
  const user = localStorage.getItem("authUser");
  const pass = localStorage.getItem("authPass");
  if (!user || !pass) {
    return {};
  }
  const token = btoa(`${user}:${pass}`);
  return { Authorization: `Basic ${token}` };
}

function updateLoginStatus() {
  const user = localStorage.getItem("authUser");
  loginStatus.textContent = user ? `Auth: ${user}` : "Auth: guest";
}

function updateQuality(minDb, maxDb) {
  if (minDb === "?" || maxDb === "?") {
    return;
  }
  const snr = Math.max(0, Number(maxDb) - Number(minDb));
  const pct = Math.min(100, Math.round((snr / 30) * 100));
  qualityBar.style.setProperty("--quality", `${pct}%`);
  qualityLabel.textContent = `SNR: ${snr.toFixed(1)} dB`;
}

function wsUrl(path) {
  const user = localStorage.getItem("authUser");
  const pass = localStorage.getItem("authPass");
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  if (user && pass) {
    return `${protocol}://${encodeURIComponent(user)}:${encodeURIComponent(pass)}@${window.location.host}${path}`;
  }
  return `${protocol}://${window.location.host}${path}`;
}

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.floor(rect.width * window.devicePixelRatio);
  canvas.height = Math.floor(rect.height * window.devicePixelRatio);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
}

resizeCanvas();
window.addEventListener("resize", resizeCanvas);

function addEvent(text) {
  const li = document.createElement("li");
  li.textContent = text;
  eventsEl.prepend(li);
}

function renderEvents(items) {
  eventsEl.innerHTML = "";
  const counts = {};
  const modeCounts = {};
  eventsTotal.textContent = String(items.length);
  if (!items.length) {
    const empty = document.createElement("li");
    empty.className = "event-empty";
    empty.textContent = "No events yet. Start a scan or adjust filters.";
    eventsEl.appendChild(empty);
  }
  items.forEach((eventItem) => {
    const li = document.createElement("li");
    li.className = "event-item";

    const header = document.createElement("div");
    header.className = "event-item__meta";

    const typeBadge = document.createElement("span");
    typeBadge.className = `badge ${eventItem.type === "callsign" ? "bg-info" : "bg-secondary"}`;
    typeBadge.textContent = eventItem.type || "event";

    const modeBadge = document.createElement("span");
    modeBadge.className = "badge bg-primary";
    modeBadge.textContent = eventItem.mode || "Unknown";

    const timeStamp = document.createElement("span");
    const timeText = eventItem.timestamp ? new Date(eventItem.timestamp).toLocaleTimeString() : "--";
    timeStamp.className = "event-item__time";
    timeStamp.textContent = timeText;

    header.appendChild(typeBadge);
    header.appendChild(modeBadge);
    header.appendChild(timeStamp);

    const body = document.createElement("div");
    body.className = "event-item__body";
    const freq = eventItem.frequency_hz ? Number(eventItem.frequency_hz).toLocaleString() : "?";
    const band = eventItem.band || "?";
    const callsign = eventItem.callsign || "-";
    body.innerHTML = `<strong>${freq} Hz</strong> <span class="event-item__muted">${band}</span> <span class="event-item__call">${callsign}</span>`;

    const detail = document.createElement("div");
    detail.className = "event-item__detail";
    if (eventItem.mode === "APRS") {
      const lat = eventItem.lat !== null && eventItem.lat !== undefined ? eventItem.lat.toFixed(3) : "--";
      const lon = eventItem.lon !== null && eventItem.lon !== undefined ? eventItem.lon.toFixed(3) : "--";
      detail.textContent = `path=${eventItem.path || "-"} | lat=${lat} lon=${lon} | ${eventItem.msg || eventItem.payload || ""}`.trim();
    } else if (eventItem.mode === "FT8" || eventItem.mode === "FT4") {
      const grid = eventItem.grid || "-";
      const report = eventItem.report || "-";
      detail.textContent = `grid=${grid} report=${report}`;
    } else if (eventItem.type === "occupancy") {
      const bw = eventItem.bandwidth_hz ? `${eventItem.bandwidth_hz} Hz` : "-";
      const snr = eventItem.snr_db !== null && eventItem.snr_db !== undefined ? `${eventItem.snr_db.toFixed(1)} dB` : "-";
      detail.textContent = `bw=${bw} snr=${snr}`;
    }

    li.appendChild(header);
    li.appendChild(body);
    if (detail.textContent) {
      li.appendChild(detail);
    }
    eventsEl.appendChild(li);
    if (eventItem.band) {
      counts[eventItem.band] = (counts[eventItem.band] || 0) + 1;
    }
    if (eventItem.mode) {
      modeCounts[eventItem.mode] = (modeCounts[eventItem.mode] || 0) + 1;
    }
  });
  bandSummary.innerHTML = "";
  if (showBandSummary.value === "on") {
    Object.entries(counts).forEach(([band, count]) => {
      const li = document.createElement("li");
      li.textContent = `${band}: ${count}`;
      bandSummary.appendChild(li);
    });
  }
  modeSummary.innerHTML = "";
  if (showModeSummary.value === "on") {
    Object.entries(modeCounts).forEach(([mode, count]) => {
      const li = document.createElement("li");
      li.textContent = `${mode}: ${count}`;
      modeSummary.appendChild(li);
    });
  }
}

async function fetchEvents() {
  try {
    const params = new URLSearchParams({ limit: "25", offset: String(eventOffset) });
    if (bandFilter.value) {
      params.append("band", bandFilter.value);
    }
    if (modeFilter.value) {
      params.append("mode", modeFilter.value);
    }
    if (callsignFilter.value) {
      params.append("callsign", callsignFilter.value.trim());
    }
    if (startFilter.value) {
      params.append("start", new Date(startFilter.value).toISOString());
    }
    if (endFilter.value) {
      params.append("end", new Date(endFilter.value).toISOString());
    }
    const resp = await fetch(`/api/events?${params.toString()}`, {
      headers: { ...getAuthHeader() }
    });
    if (resp.status === 401) {
      showToastError("Authentication failed");
      return;
    }
    const data = await resp.json();
    renderEvents(data);
    pageOffsetLabel.textContent = `Offset: ${eventOffset}`;
    pageNumberLabel.textContent = `Page: ${Math.floor(eventOffset / 25) + 1}`;
    localStorage.setItem("filters", JSON.stringify({
      band: bandFilter.value,
      mode: modeFilter.value,
      callsign: callsignFilter.value,
      start: startFilter.value,
      end: endFilter.value
    }));
    localStorage.setItem("summary", JSON.stringify({
      showBand: showBandSummary.value === "on",
      showMode: showModeSummary.value === "on"
    }));
  } catch (err) {
    addEvent("Failed to load events");
  }
}

async function fetchTotal() {
  try {
    const params = new URLSearchParams({});
    if (bandFilter.value) {
      params.append("band", bandFilter.value);
    }
    if (modeFilter.value) {
      params.append("mode", modeFilter.value);
    }
    if (callsignFilter.value) {
      params.append("callsign", callsignFilter.value.trim());
    }
    if (startFilter.value) {
      params.append("start", new Date(startFilter.value).toISOString());
    }
    if (endFilter.value) {
      params.append("end", new Date(endFilter.value).toISOString());
    }
    const resp = await fetch(`/api/events/count?${params.toString()}`, {
      headers: { ...getAuthHeader() }
    });
    if (!resp.ok) {
      return;
    }
    const data = await resp.json();
    totalGlobal.textContent = `Total: ${data.total}`;
  } catch (err) {
    return;
  }
}

async function fetchModeStats() {
  try {
    const resp = await fetch("/api/events/stats", { headers: { ...getAuthHeader() } });
    if (!resp.ok) {
      return;
    }
    const data = await resp.json();
    modeStatsCache = data.modes || {};
    modeSummary.innerHTML = "";
    Object.entries(modeStatsCache).forEach(([mode, count]) => {
      const li = document.createElement("li");
      li.textContent = `${mode}: ${count}`;
      modeSummary.appendChild(li);
    });
  } catch (err) {
    return;
  }
}

async function fetchLogs() {
  try {
    const resp = await fetch("/api/logs?limit=50", { headers: { ...getAuthHeader() } });
    if (!resp.ok) {
      return;
    }
    const data = await resp.json();
    logsEl.textContent = data.join("\n");
  } catch (err) {
    return;
  }
}

function connectLogs() {
  try {
    const ws = new WebSocket(wsUrl("/ws/logs"));
    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data);
        if (Array.isArray(data.logs)) {
          logsEl.textContent = data.logs.join("\n");
        }
      } catch (err) {
        return;
      }
    };
  } catch (err) {
    return;
  }
}

function setStatus(text) {
  statusEl.textContent = text;
}

startBtn.addEventListener("click", async () => {
  setStatus("Starting scan...");
  const gain = Number(gainInput.value);
  const sampleRate = Number(sampleRateInput.value);
  const recordPath = recordPathInput.value || null;
  await fetch("/api/scan/start", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeader() },
    body: JSON.stringify({
      scan: {
        band: bandSelect.value,
        start_hz: 14000000,
        end_hz: 14350000,
        step_hz: 2000,
        dwell_ms: 250,
        mode: "auto",
        gain,
        sample_rate: sampleRate,
        record_path: recordPath,
        device_id: deviceSelect.value || null
      }
    })
  });
  setStatus("Scan running");
  logLine("Scan started");
});

stopBtn.addEventListener("click", async () => {
  setStatus("Stopping scan...");
  await fetch("/api/scan/stop", { method: "POST", headers: { ...getAuthHeader() } });
  setStatus("Scan stopped");
  logLine("Scan stopped");
});

function connectEvents() {
  try {
    const ws = new WebSocket(wsUrl("/ws/events"));
    ws.onopen = () => addEvent("Connected to events stream");
    ws.onmessage = (msg) => addEvent(msg.data);
    ws.onerror = () => addEvent("Events stream error");
    ws.onclose = () => {
      wsStatus.textContent = "WS: disconnected";
    };
  } catch (err) {
    addEvent("WebSocket not available");
  }
}

connectEvents();
fetchEvents();
setInterval(fetchEvents, 5000);

bandFilter.addEventListener("change", fetchEvents);
modeFilter.addEventListener("change", fetchEvents);
callsignFilter.addEventListener("change", fetchEvents);
startFilter.addEventListener("change", fetchEvents);
endFilter.addEventListener("change", fetchEvents);
bandFilter.addEventListener("change", fetchTotal);
modeFilter.addEventListener("change", fetchTotal);
callsignFilter.addEventListener("change", fetchTotal);
startFilter.addEventListener("change", fetchTotal);
endFilter.addEventListener("change", fetchTotal);

exportCsvBtn.addEventListener("click", () => {
  exportCsvBtn.disabled = true;
  exportCsvBtn.textContent = "Exporting...";
  const params = new URLSearchParams({ limit: "1000", format: "csv" });
  if (bandFilter.value) {
    params.append("band", bandFilter.value);
  }
  if (modeFilter.value) {
    params.append("mode", modeFilter.value);
  }
  if (callsignFilter.value) {
    params.append("callsign", callsignFilter.value.trim());
  }
  if (startFilter.value) {
    params.append("start", new Date(startFilter.value).toISOString());
  }
  if (endFilter.value) {
    params.append("end", new Date(endFilter.value).toISOString());
  }
  window.location.href = `/api/export?${params.toString()}`;
  setTimeout(() => {
    exportCsvBtn.disabled = false;
    exportCsvBtn.textContent = "Export CSV";
  }, 1500);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "s") {
    startBtn.click();
  }
  if (event.key === "x") {
    stopBtn.click();
  }
});

function connectSpectrum() {
  try {
    const ws = new WebSocket(wsUrl("/ws/spectrum"));
    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data);
        const frame = decodeSpectrumFrame(data.spectrum_frame);
        if (frame && frame.fft_db) {
          drawWaterfall(frame);
          const startHz = Math.round(frame.center_hz - frame.span_hz / 2);
          const endHz = Math.round(frame.center_hz + frame.span_hz / 2);
          const minDb = frame.min_db !== undefined ? frame.min_db.toFixed(1) : "?";
          const maxDb = frame.max_db !== undefined ? frame.max_db.toFixed(1) : "?";
          const noiseFloor = frame.noise_floor_db !== undefined ? frame.noise_floor_db.toFixed(1) : "?";
          const agcGain = frame.agc_gain_db !== undefined && frame.agc_gain_db !== null
            ? frame.agc_gain_db.toFixed(1)
            : null;
          let peaksInfo = "";
          if (Array.isArray(frame.peaks) && frame.peaks.length) {
            const topPeaks = frame.peaks.slice(0, 3).map((peak) => {
              const hz = Math.round(peak.offset_hz ?? 0);
              const snr = peak.snr_db !== undefined ? peak.snr_db.toFixed(1) : "?";
              return `${hz}Hz/${snr}dB`;
            });
            peaksInfo = ` | peaks ${frame.peaks.length}: ${topPeaks.join(", ")}`;
          }
          const agcInfo = agcGain ? ` | agc ${agcGain}dB` : "";
          waterfallStatus.textContent = `FFT bins: ${frame.fft_db.length} | ${startHz} Hz - ${endHz} Hz | dB ${minDb}..${maxDb} | nf ${noiseFloor}dB${peaksInfo}${agcInfo}`;
          updateQuality(minDb, maxDb);
        }
      } catch (err) {
        waterfallStatus.textContent = "Spectrum decode error";
      }
    };
    ws.onopen = () => {
      wsStatus.textContent = "WS: connected";
    };
    ws.onclose = () => {
      wsStatus.textContent = "WS: disconnected";
    };
  } catch (err) {
    waterfallStatus.textContent = "Spectrum stream unavailable";
  }
}

connectSpectrum();

function decodeSpectrumFrame(frame) {
  if (!frame) {
    return frame;
  }
  if (Array.isArray(frame.fft_db)) {
    return frame;
  }
  if (frame.encoding !== "delta_int8" || !Array.isArray(frame.fft_delta)) {
    return frame;
  }
  const ref = Number(frame.fft_ref_db ?? 0);
  const step = Number(frame.fft_step_db ?? 0.5) || 0.5;
  const fftDb = frame.fft_delta.map((value) => ref + (Number(value) + 128) * step);
  return {
    ...frame,
    fft_db: fftDb
  };
}

function connectStatus() {
  try {
    const ws = new WebSocket(wsUrl("/ws/status"));
    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data);
        const status = data.status;
        if (status) {
          const nf = status.noise_floor_db !== undefined ? status.noise_floor_db.toFixed(1) : "?";
          const threshold = status.threshold_db !== undefined ? status.threshold_db.toFixed(1) : "?";
          const agc = status.agc_gain_db !== undefined && status.agc_gain_db !== null
            ? status.agc_gain_db.toFixed(1)
            : "?";
          statusEl.textContent = `state=${status.state} cpu=${status.cpu_pct ?? "?"}% noise=${nf}dB thr=${threshold}dB agc=${agc}dB frameAge=${status.frame_age_ms ?? "?"}ms`;
        }
      } catch (err) {
        setStatus("Status decode error");
      }
    };
  } catch (err) {
    setStatus("Status stream unavailable");
  }
}

connectStatus();

async function fetchDecoderStatus() {
  if (!decoderStatusEl) {
    return;
  }
  try {
    const resp = await fetch("/api/decoders/status", { headers: { ...getAuthHeader() } });
    if (!resp.ok) {
      throw new Error("decoder status failed");
    }
    const data = await resp.json();
    const status = data.status || {};
    const wsjtx = status.wsjtx_udp || {};
    const kiss = status.direwolf_kiss || {};
    const sources = status.sources || {};
    const lastEvent = Object.values(sources).sort().slice(-1)[0] || "-";
    wsjtxUdpStatusEl.textContent = wsjtx.enabled ? `Listening ${wsjtx.listen || "?"}` : "Disabled";
    const kissState = kiss.enabled ? (kiss.connected ? "Connected" : "Disconnected") : "Disabled";
    kissStatusEl.textContent = kissState;
    decoderLastEventEl.textContent = lastEvent;
    agcStatusEl.textContent = status.dsp && status.dsp.agc_enabled ? "On" : "Off";
  } catch (err) {
    wsjtxUdpStatusEl.textContent = "Unavailable";
    kissStatusEl.textContent = "Unavailable";
    decoderLastEventEl.textContent = "-";
    agcStatusEl.textContent = "-";
  }
}

async function loadDevices() {
  try {
    const resp = await fetch("/api/devices", { headers: { ...getAuthHeader() } });
    const devices = await resp.json();
    deviceSelect.innerHTML = "";
    devices.forEach((device) => {
      const option = document.createElement("option");
      option.value = device.id;
      option.textContent = device.name;
      deviceSelect.appendChild(option);
    });
  } catch (err) {
    logLine("Failed to load devices");
  }
}

async function loadBands() {
  try {
    const resp = await fetch("/api/bands", { headers: { ...getAuthHeader() } });
    const bands = await resp.json();
    if (Array.isArray(bands) && bands.length) {
      bandSelect.innerHTML = "";
      bands.forEach((band) => {
        const option = document.createElement("option");
        option.value = band.name;
        option.textContent = band.name;
        bandSelect.appendChild(option);
      });
    }
  } catch (err) {
    logLine("Failed to load bands");
  }
}

async function loadSettings() {
  const authUser = localStorage.getItem("authUser") || "";
  const authPass = localStorage.getItem("authPass") || "";
  authUserInput.value = authUser;
  authPassInput.value = authPass;
  loginUserInput.value = authUser;
  loginPassInput.value = authPass;

  try {
    const resp = await fetch("/api/settings", { headers: { ...getAuthHeader() } });
    const data = await resp.json();
    if (data.band) {
      if (typeof data.band === "string") {
        bandSelect.value = data.band;
      } else if (data.band.name) {
        bandSelect.value = data.band.name;
        bandNameInput.value = data.band.name;
        bandStartInput.value = data.band.start_hz ?? bandStartInput.value;
        bandEndInput.value = data.band.end_hz ?? bandEndInput.value;
      }
    }
    if (data.device_id) {
      deviceSelect.value = data.device_id;
    }
    if (Array.isArray(data.favorites)) {
      localStorage.setItem("favoriteBands", JSON.stringify(data.favorites));
      loadFavorites();
    }
    if (data.modes) {
      ft8Toggle.value = data.modes.ft8 ? "on" : "off";
      aprsToggle.value = data.modes.aprs ? "on" : "off";
      cwToggle.value = data.modes.cw ? "on" : "off";
      ssbToggle.value = data.modes.ssb ? "on" : "off";
    }
    if (data.summary) {
      showBandSummary.value = data.summary.showBand ? "on" : "off";
      showModeSummary.value = data.summary.showMode ? "on" : "off";
    }
  } catch (err) {
    logLine("Failed to load settings");
  }
}

saveModesBtn.addEventListener("click", async () => {
  const payload = {
    modes: {
      ft8: ft8Toggle.value === "on",
      aprs: aprsToggle.value === "on",
      cw: cwToggle.value === "on",
      ssb: ssbToggle.value === "on"
    }
  };
  await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeader() },
    body: JSON.stringify(payload)
  });
  showToast("Modes saved");
});

showBandSummary.addEventListener("change", () => {
  persistSummary();
  fetchEvents();
});

showModeSummary.addEventListener("change", () => {
  persistSummary();
  fetchEvents();
});

function persistSummary() {
  const summary = {
    showBand: showBandSummary.value === "on",
    showMode: showModeSummary.value === "on"
  };
  localStorage.setItem("summary", JSON.stringify(summary));
  fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeader() },
    body: JSON.stringify({ summary })
  });
}

prevPageBtn.addEventListener("click", () => {
  eventOffset = Math.max(0, eventOffset - 25);
  fetchEvents();
});

nextPageBtn.addEventListener("click", () => {
  eventOffset += 25;
  fetchEvents();
});

compactToggle.addEventListener("click", () => {
  const panel = compactToggle.closest(".filters");
  panel.classList.toggle("compact");
});

loginSaveBtn.addEventListener("click", () => {
  localStorage.setItem("authUser", loginUserInput.value);
  localStorage.setItem("authPass", loginPassInput.value);
  showToast("Credentials saved");
  updateLoginStatus();
});

const onboardingSteps = [
  {
    title: "Welcome",
    text: "Configure device, band, and credentials. Use Start or press s."
  },
  {
    title: "Scan",
    text: "Select band, gain, and sample rate. Start scan and watch the waterfall."
  },
  {
    title: "Events",
    text: "Use filters to narrow events and export CSV reports."
  }
];
let onboardingStep = 0;

function renderOnboarding() {
  const step = onboardingSteps[onboardingStep];
  onboardingTitle.textContent = step.title;
  onboardingText.textContent = step.text;
  onboardingPrev.disabled = onboardingStep === 0;
  onboardingNext.textContent = onboardingStep === onboardingSteps.length - 1 ? "Done" : "Next";
}

onboardingPrev.addEventListener("click", () => {
  if (onboardingStep > 0) {
    onboardingStep -= 1;
    renderOnboarding();
  }
});

onboardingNext.addEventListener("click", () => {
  if (onboardingStep < onboardingSteps.length - 1) {
    onboardingStep += 1;
    renderOnboarding();
    return;
  }
  onboarding.classList.remove("show");
  localStorage.setItem("onboardingDone", "1");
});

function loadFilters() {
  const data = JSON.parse(localStorage.getItem("filters") || "{}")
  if (data.band) bandFilter.value = data.band;
  if (data.mode) modeFilter.value = data.mode;
  if (data.callsign) callsignFilter.value = data.callsign;
  if (data.start) startFilter.value = data.start;
  if (data.end) endFilter.value = data.end;
}

saveSettingsBtn.addEventListener("click", async () => {
  localStorage.setItem("authUser", authUserInput.value);
  localStorage.setItem("authPass", authPassInput.value);
  const payload = {
    band: bandSelect.value,
    device_id: deviceSelect.value
  };
  await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeader() },
    body: JSON.stringify(payload)
  });
  logLine("Settings saved");
});

refreshDevicesBtn.addEventListener("click", () => {
  loadDevices();
});

saveBandBtn.addEventListener("click", async () => {
  const payload = {
    band: {
      name: bandNameInput.value,
      start_hz: Number(bandStartInput.value),
      end_hz: Number(bandEndInput.value)
    }
  };
  const resp = await fetch("/api/bands", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeader() },
    body: JSON.stringify(payload)
  });
  if (!resp.ok) {
    showToast("Band validation failed");
    return;
  }
  logLine("Band saved");
  showToast("Band saved");
  loadBands();
});

loadDevices().then(loadBands).then(loadSettings).then(loadPresets).then(loadFavorites).then(loadFilters).then(fetchTotal);
fetchModeStats();
setInterval(fetchModeStats, 10000);
fetchDecoderStatus();
setInterval(fetchDecoderStatus, 10000);
updateLoginStatus();
connectLogs();
fetchLogs();
setInterval(fetchLogs, 4000);

if (!localStorage.getItem("onboardingDone")) {
  onboarding.classList.add("show");
  renderOnboarding();
}

function drawWaterfall(frame) {
  const fftDb = frame.fft_db || [];
  const width = canvas.width / window.devicePixelRatio;
  const height = canvas.height / window.devicePixelRatio;
  if (!fftDb.length) {
    return;
  }

  let minDb = Infinity;
  let maxDb = -Infinity;
  for (let i = 0; i < fftDb.length; i += 1) {
    const value = fftDb[i];
    if (value < minDb) {
      minDb = value;
    }
    if (value > maxDb) {
      maxDb = value;
    }
  }
  const scale = maxDb - minDb || 1;
  const rowData = ctx.createImageData(Math.floor(width), 1);

  for (let x = 0; x < width; x += 1) {
    const idx = Math.floor((x / width) * fftDb.length);
    const value = (fftDb[idx] - minDb) / scale;
    const color = colorMap(value);
    const offset = x * 4;
    rowData.data[offset] = color[0];
    rowData.data[offset + 1] = color[1];
    rowData.data[offset + 2] = color[2];
    rowData.data[offset + 3] = 255;
  }

  ctx.putImageData(rowData, 0, row);
  if (Array.isArray(frame.peaks) && frame.peaks.length && frame.span_hz) {
    ctx.save();
    ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
    const span = frame.span_hz;
    frame.peaks.forEach((peak) => {
      const offset = peak.offset_hz ?? 0;
      const x = Math.round(((offset + span / 2) / span) * width);
      ctx.fillRect(x, row, 2, 1);
    });
    ctx.restore();
  }
  row = (row + 1) % height;
  if (row === 0) {
    ctx.clearRect(0, 0, width, height);
  }
}

function colorMap(value) {
  const r = Math.floor(255 * value);
  const g = Math.floor(140 + 80 * (1 - value));
  const b = Math.floor(255 * (1 - value));
  return [r, g, b];
}
