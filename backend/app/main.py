from fastapi import FastAPI

app = FastAPI(title="4ham Spectrum Analysis")

_scan_state = {
    "state": "stopped",
    "device": None,
    "started_at": None
}


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": "0.1.0",
        "devices": 0
    }


@app.get("/api/devices")
def devices():
    return []


@app.get("/api/bands")
def bands():
    return []


@app.post("/api/scan/start")
def scan_start(payload: dict):
    _scan_state["state"] = "running"
    _scan_state["device"] = payload.get("device", "rtl_sdr")
    _scan_state["started_at"] = "pending"
    return _scan_state


@app.post("/api/scan/stop")
def scan_stop():
    _scan_state["state"] = "stopped"
    return _scan_state


@app.get("/api/events")
def events():
    return []
