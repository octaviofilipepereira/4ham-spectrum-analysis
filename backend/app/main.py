import asyncio
import os
from datetime import datetime, timezone

import numpy as np
from fastapi import FastAPI, WebSocket

from app.dsp.pipeline import compute_fft_db, estimate_occupancy
from app.scan.engine import ScanEngine
from app.sdr.controller import SDRController
from app.storage.db import Database

app = FastAPI(title="4ham Spectrum Analysis")

_controller = SDRController()
_scan_engine = ScanEngine(_controller)
os.makedirs("data", exist_ok=True)
_db = Database("data/events.sqlite")
_scan_state = {
    "state": "stopped",
    "device": None,
    "started_at": None,
    "scan": None,
    "scan_id": None
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
async def scan_start(payload: dict):
    scan = payload.get("scan", {})
    await _scan_engine.start_async(scan)
    _scan_state["state"] = "running"
    _scan_state["device"] = payload.get("device", "rtl_sdr")
    _scan_state["started_at"] = datetime.now(timezone.utc).isoformat()
    _scan_state["scan"] = scan
    _scan_state["scan_id"] = _db.start_scan(scan, _scan_state["started_at"])
    return _scan_state


@app.post("/api/scan/stop")
async def scan_stop():
    await _scan_engine.stop_async()
    _scan_state["state"] = "stopped"
    _db.end_scan(_scan_state.get("scan_id"), datetime.now(timezone.utc).isoformat())
    return _scan_state


@app.get("/api/events")
def events(limit: int = 1000):
    return _db.get_events(limit=limit)


@app.get("/api/scans")
def scans(limit: int = 100):
    return _db.get_scans(limit=limit)


@app.get("/api/scan/status")
def scan_status():
    return _scan_state


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    await websocket.accept()
    while True:
        iq = _scan_engine.read_iq(2048)
        if iq is None:
            iq = (np.random.randn(2048) + 1j * np.random.randn(2048)) * 0.02
        occupancy = estimate_occupancy(iq, _scan_engine.sample_rate)
        if occupancy:
            event = {
                "type": "occupancy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "band": _scan_engine.config.get("band") if _scan_engine.config else None,
                "frequency_hz": _scan_engine.center_hz,
                "bandwidth_hz": occupancy[0]["bandwidth_hz"],
                "power_dbm": occupancy[0]["power_dbm"],
                "snr_db": None,
                "threshold_dbm": occupancy[0]["threshold_dbm"],
                "occupied": occupancy[0]["occupied"],
                "mode": "Unknown",
                "confidence": 0.4,
                "device": _scan_state.get("device"),
                "scan_id": _scan_state.get("scan_id")
            }
            _db.insert_occupancy(event)
            await websocket.send_json({"event": event})
            await asyncio.sleep(1.0)
            continue

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
    while True:
        iq = _scan_engine.read_iq(2048)
        if iq is None:
            iq = (np.random.randn(2048) + 1j * np.random.randn(2048)) * 0.02
        fft_db, bin_hz, min_db, max_db = compute_fft_db(iq, _scan_engine.sample_rate)
        payload = {
            "spectrum_frame": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "center_hz": _scan_engine.center_hz,
                "span_hz": _scan_engine.sample_rate,
                "bin_hz": bin_hz,
                "fft_db": fft_db,
                "min_db": min_db,
                "max_db": max_db
            }
        }
        await websocket.send_json(payload)
        await asyncio.sleep(0.2)
