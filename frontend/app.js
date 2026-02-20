const statusEl = document.getElementById("status");
const eventsEl = document.getElementById("events");
const waterfallEl = document.getElementById("waterfall");
const waterfallStatus = document.getElementById("waterfallStatus");
const canvas = document.getElementById("waterfallCanvas");
const ctx = canvas.getContext("2d");
const gainInput = document.getElementById("gain");
const sampleRateInput = document.getElementById("sampleRate");
const startBtn = document.getElementById("startScan");
const stopBtn = document.getElementById("stopScan");
let row = 0;

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
    const resp = await fetch("/api/events?limit=25");
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
  await fetch("/api/scan/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      scan: {
        band: "20m",
        start_hz: 14000000,
        end_hz: 14350000,
        step_hz: 2000,
        dwell_ms: 250,
        mode: "auto",
        gain,
        sample_rate: sampleRate
      }
    })
  });
  setStatus("Scan running");
});

stopBtn.addEventListener("click", async () => {
  setStatus("Stopping scan...");
  await fetch("/api/scan/stop", { method: "POST" });
  setStatus("Scan stopped");
});

function connectEvents() {
  try {
    const ws = new WebSocket("ws://localhost:8000/ws/events");
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

function connectSpectrum() {
  try {
    const ws = new WebSocket("ws://localhost:8000/ws/spectrum");
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
    const ws = new WebSocket("ws://localhost:8000/ws/status");
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
