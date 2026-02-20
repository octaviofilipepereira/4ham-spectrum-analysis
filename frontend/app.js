const statusEl = document.getElementById("status");
const eventsEl = document.getElementById("events");
const waterfallEl = document.getElementById("waterfall");
const waterfallStatus = document.getElementById("waterfallStatus");
const canvas = document.getElementById("waterfallCanvas");
const ctx = canvas.getContext("2d");
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

function setStatus(text) {
  statusEl.textContent = text;
}

startBtn.addEventListener("click", async () => {
  setStatus("Starting scan...");
  await fetch("/api/scan/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scan: { band: "20m", start_hz: 14000000, end_hz: 14350000, step_hz: 2000, dwell_ms: 250, mode: "auto" } })
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

function connectSpectrum() {
  try {
    const ws = new WebSocket("ws://localhost:8000/ws/spectrum");
    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data);
        const frame = data.spectrum_frame;
        if (frame && frame.fft_db) {
          drawWaterfall(frame.fft_db);
          waterfallStatus.textContent = `FFT bins: ${frame.fft_db.length} | center ${frame.center_hz}`;
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
