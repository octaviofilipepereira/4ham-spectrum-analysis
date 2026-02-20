from datetime import datetime, timezone

from fastapi import FastAPI

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
