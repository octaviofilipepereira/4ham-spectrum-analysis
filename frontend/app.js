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
const startBtn = document.getElementById("startScan");
const stopBtn = document.getElementById("stopScan");
let row = 0;

function logLine(text) {
  const current = logsEl.textContent === "No logs yet." ? "" : logsEl.textContent;
  logsEl.textContent = `${new Date().toISOString()} ${text}\n${current}`.trim();
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

function getAuthHeader() {
  const user = localStorage.getItem("authUser");
  const pass = localStorage.getItem("authPass");
  if (!user || !pass) {
    return {};
  }
  const token = btoa(`${user}:${pass}`);
  return { Authorization: `Basic ${token}` };
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
  items.forEach((eventItem) => {
    const label = `${eventItem.type} | ${eventItem.band || "?"} | ${eventItem.frequency_hz} Hz`;
    addEvent(label);
  });
}

async function fetchEvents() {
  try {
    const params = new URLSearchParams({ limit: "25" });
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
    const data = await resp.json();
    renderEvents(data);
  } catch (err) {
    addEvent("Failed to load events");
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

exportCsvBtn.addEventListener("click", () => {
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
        const frame = data.spectrum_frame;
        if (frame && frame.fft_db) {
          drawWaterfall(frame.fft_db);
          const startHz = Math.round(frame.center_hz - frame.span_hz / 2);
          const endHz = Math.round(frame.center_hz + frame.span_hz / 2);
          const minDb = frame.min_db !== undefined ? frame.min_db.toFixed(1) : "?";
          const maxDb = frame.max_db !== undefined ? frame.max_db.toFixed(1) : "?";
          waterfallStatus.textContent = `FFT bins: ${frame.fft_db.length} | ${startHz} Hz - ${endHz} Hz | dB ${minDb}..${maxDb}`;
        }
      } catch (err) {
        waterfallStatus.textContent = "Spectrum decode error";
      }
    };
  } catch (err) {
    waterfallStatus.textContent = "Spectrum stream unavailable";
  }
}

connectSpectrum();

function connectStatus() {
  try {
    const ws = new WebSocket(wsUrl("/ws/status"));
    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data);
        const status = data.status;
        if (status) {
          const nf = status.noise_floor_db !== undefined ? status.noise_floor_db.toFixed(1) : "?";
          statusEl.textContent = `state=${status.state} cpu=${status.cpu_pct ?? "?"}% noise=${nf}dB frameAge=${status.frame_age_ms ?? "?"}ms`;
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
  } catch (err) {
    logLine("Failed to load settings");
  }
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
  await fetch("/api/bands", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeader() },
    body: JSON.stringify(payload)
  });
  logLine("Band saved");
  loadBands();
});

loadDevices().then(loadBands).then(loadSettings).then(loadPresets);

function drawWaterfall(fftDb) {
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
