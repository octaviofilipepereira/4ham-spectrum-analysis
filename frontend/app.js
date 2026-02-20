const statusEl = document.getElementById("status");
const eventsEl = document.getElementById("events");
const startBtn = document.getElementById("startScan");
const stopBtn = document.getElementById("stopScan");

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
