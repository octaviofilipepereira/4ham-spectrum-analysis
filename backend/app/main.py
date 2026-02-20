import asyncio
from datetime import datetime, timezone

import numpy as np
from fastapi import FastAPI, WebSocket

from app.dsp.pipeline import compute_fft_db
from app.scan.engine import ScanEngine
from app.sdr.controller import SDRController

app = FastAPI(title="4ham Spectrum Analysis")

_controller = SDRController()
_scan_engine = ScanEngine(_controller)
_scan_state = {
    "state": "stopped",
    "device": None,
    "started_at": None,
    "scan": None
}


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": "0.1.0",
        "devices": len(_controller.list_devices())
    }


@app.get("/api/devices")
def devices():
    return _controller.list_devices()


@app.get("/api/bands")
def bands():
    return []


@app.post("/api/scan/start")
def scan_start(payload: dict):
    scan = payload.get("scan", {})
    _scan_engine.start(scan)
    _scan_state["state"] = "running"
    _scan_state["device"] = payload.get("device", "rtl_sdr")
    _scan_state["started_at"] = datetime.now(timezone.utc).isoformat()
    _scan_state["scan"] = scan
    return _scan_state


@app.post("/api/scan/stop")
def scan_stop():
    _scan_engine.stop()
    _scan_state["state"] = "stopped"
    return _scan_state


@app.get("/api/events")
def events():
    return []


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    await websocket.accept()
    while True:
        payload = {
            "event": {
                "type": "occupancy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "band": "20m",
                "frequency_hz": 14074000,
                "bandwidth_hz": 2700,
                "power_dbm": -90.0,
                "snr_db": 6.0,
                "threshold_dbm": -98.0,
                "occupied": True,
                "mode": "SSB",
                "confidence": 0.6,
                "device": _scan_state.get("device")
            }
        }
        await websocket.send_json(payload)
        await asyncio.sleep(2.0)


@app.websocket("/ws/spectrum")
async def ws_spectrum(websocket: WebSocket):
    await websocket.accept()
    sample_rate = 48000
    while True:
        iq = (np.random.randn(2048) + 1j * np.random.randn(2048)) * 0.02
        fft_db, bin_hz = compute_fft_db(iq, sample_rate)
        payload = {
            "spectrum_frame": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "center_hz": 14074000,
                "span_hz": sample_rate,
                "bin_hz": bin_hz,
                "fft_db": fft_db
            }
        }
        await websocket.send_json(payload)
        await asyncio.sleep(0.2)
