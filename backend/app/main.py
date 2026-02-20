import asyncio
import os
import time
from datetime import datetime, timezone

import numpy as np
from fastapi import FastAPI, WebSocket

from app.dsp.pipeline import compute_fft_db, compute_power_db, estimate_occupancy
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
_spectrum_cache = {
    "fft_db": None,
    "bin_hz": None,
    "min_db": None,
    "max_db": None,
    "timestamp": None,
    "center_hz": 0,
    "span_hz": 0
}
_noise_floor = {}
_last_frame_ts = None
_last_send_ts = None


def _update_noise_floor(band, power_db, alpha=0.05):
    if not band:
        return power_db
    current = _noise_floor.get(band)
    if current is None:
        _noise_floor[band] = power_db
    else:
        _noise_floor[band] = (1 - alpha) * current + alpha * power_db
    return _noise_floor[band]


def _cpu_percent():
    try:
        import psutil
    except Exception:
        return None
    return psutil.cpu_percent(interval=None)


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
def events(limit: int = 1000, band: str | None = None, mode: str | None = None):
    return _db.get_events(limit=limit, band=band, mode=mode)


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
        band = _scan_engine.config.get("band") if _scan_engine.config else None
        power_db = compute_power_db(iq)
        noise_floor = _update_noise_floor(band, power_db)
        threshold_dbm = noise_floor + 6.0
        occupancy = estimate_occupancy(
            iq,
            _scan_engine.sample_rate,
            threshold_dbm=threshold_dbm,
            adapt=False
        )
        if occupancy:
            event = {
                "type": "occupancy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "band": band,
                "frequency_hz": _scan_engine.center_hz,
                "bandwidth_hz": occupancy[0]["bandwidth_hz"],
                "power_dbm": power_db,
                "snr_db": None,
                "threshold_dbm": threshold_dbm,
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
        frame_start = time.time()
        iq = _scan_engine.read_iq(2048)
        if iq is None:
            iq = (np.random.randn(2048) + 1j * np.random.randn(2048)) * 0.02
        fft_db, bin_hz, min_db, max_db = compute_fft_db(iq, _scan_engine.sample_rate, smooth_bins=6)
        global _last_frame_ts
        _last_frame_ts = time.time()
        _spectrum_cache.update({
            "fft_db": fft_db,
            "bin_hz": bin_hz,
            "min_db": min_db,
            "max_db": max_db,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "center_hz": _scan_engine.center_hz,
            "span_hz": _scan_engine.sample_rate
        })
        payload = {
            "spectrum_frame": {
                "timestamp": _spectrum_cache["timestamp"],
                "center_hz": _spectrum_cache["center_hz"],
                "span_hz": _spectrum_cache["span_hz"],
                "bin_hz": bin_hz,
                "fft_db": fft_db,
                "min_db": min_db,
                "max_db": max_db
            }
        }
        await websocket.send_json(payload)
        global _last_send_ts
        _last_send_ts = time.time()
        await asyncio.sleep(0.2)


@app.websocket("/ws/status")
async def ws_status(websocket: WebSocket):
    await websocket.accept()
    while True:
        now = time.time()
        frame_age_ms = None
        if _last_frame_ts:
            frame_age_ms = int((now - _last_frame_ts) * 1000)
        band = _scan_engine.config.get("band") if _scan_engine.config else None
        payload = {
            "status": {
                "state": _scan_state.get("state"),
                "device": _scan_state.get("device"),
                "cpu_pct": _cpu_percent(),
                "frame_age_ms": frame_age_ms,
                "noise_floor_db": _noise_floor.get(band)
            }
        }
        await websocket.send_json(payload)
        await asyncio.sleep(1.0)
