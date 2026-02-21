import asyncio
import os
import time
import base64
from datetime import datetime, timezone

import numpy as np
from fastapi import FastAPI, WebSocket, Request, HTTPException, status
from fastapi.responses import PlainTextResponse

from app.config.loader import (
    ConfigError,
    apply_region_profile_to_scan,
    load_region_profile,
    load_scan_request,
)
from app.decoders.ingest import build_callsign_event
from app.decoders.parsers import parse_wsjtx_line, parse_aprs_line, parse_cw_text
from app.decoders.watchers import tail_lines, tail_from_end_default
from app.decoders.wsjtx_udp import WsjtxState, create_wsjtx_udp_listener, describe_wsjtx_udp
from app.decoders.direwolf_kiss import kiss_loop, describe_kiss
from app.dsp.pipeline import (
    compute_fft_db,
    compute_power_db,
    estimate_occupancy,
    detect_peaks,
    estimate_noise_floor,
    apply_agc_smoothed
)
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
_logs = []
_count_cache = {
    "timestamp": 0.0,
    "value": 0,
    "key": None
}
_decoder_tasks = []
_decoder_stop = asyncio.Event()
_wsjtx_state = WsjtxState()
_wsjtx_transport = None
_kiss_task = None
_threshold_state = {}


def _env_float(name, default):
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return float(default)


def _env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return int(default)


_agc_enabled = os.getenv("DSP_AGC_ENABLE", "0").lower() in {"1", "true", "yes", "on"}
_agc_target_rms = _env_float("DSP_AGC_TARGET_RMS", 0.25)
_agc_max_gain_db = _env_float("DSP_AGC_MAX_GAIN_DB", 30.0)
_agc_alpha = _env_float("DSP_AGC_ALPHA", 0.2)
_snr_threshold_db = _env_float("DSP_SNR_THRESHOLD_DB", 6.0)
_min_bw_hz = _env_int("DSP_MIN_BW_HZ", 500)
_agc_state = {}
_last_agc_gain_db = None
_decoder_status = {
    "sources": {},
    "wsjtx_udp": {
        "enabled": False,
        "listen": None,
        "last_packet_at": None
    },
    "direwolf_kiss": {
        "enabled": False,
        "address": None,
        "connected": False,
        "last_packet_at": None,
        "last_error": None
    },
    "files": {
        "wsjtx": None,
        "aprs": None,
        "cw": None
    },
    "dsp": {
        "agc_enabled": _agc_enabled,
        "agc_target_rms": _agc_target_rms,
        "agc_max_gain_db": _agc_max_gain_db,
        "agc_alpha": _agc_alpha,
        "snr_threshold_db": _snr_threshold_db,
        "min_bw_hz": _min_bw_hz
    }
}

_auth_user = os.getenv("BASIC_AUTH_USER")
_auth_pass = os.getenv("BASIC_AUTH_PASS")


def _auth_required():
    return bool(_auth_user and _auth_pass)


def _verify_basic_auth(auth_header):
    if not auth_header:
        return False
    if not auth_header.lower().startswith("basic "):
        return False
    try:
        encoded = auth_header.split(" ", 1)[1].strip()
        decoded = base64.b64decode(encoded).decode("utf-8")
    except Exception:
        return False
    if ":" not in decoded:
        return False
    username, password = decoded.split(":", 1)
    return username == _auth_user and password == _auth_pass


def _enforce_auth(request: Request):
    if not _auth_required():
        return
    auth_header = request.headers.get("authorization")
    if not _verify_basic_auth(auth_header):
        _log("auth_failed")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


def _update_noise_floor(band, power_db, alpha=0.05):
    if not band:
        return power_db
    current = _noise_floor.get(band)
    if current is None:
        _noise_floor[band] = power_db
    else:
        _noise_floor[band] = (1 - alpha) * current + alpha * power_db
    return _noise_floor[band]


def _update_threshold(band, threshold_db, alpha=0.1):
    if band is None or threshold_db is None:
        return threshold_db
    current = _threshold_state.get(band)
    if current is None:
        _threshold_state[band] = threshold_db
    else:
        _threshold_state[band] = (1 - alpha) * current + alpha * threshold_db
    return _threshold_state[band]


def _cpu_percent():
    try:
        import psutil
    except Exception:
        return None
    return psutil.cpu_percent(interval=None)


def _log(message):
    timestamp = datetime.now(timezone.utc).isoformat()
    _logs.append(f"{timestamp} {message}")
    if len(_logs) > 500:
        _logs.pop(0)


def _touch_decoder_source(source):
    if not source:
        return
    _decoder_status["sources"][source] = datetime.now(timezone.utc).isoformat()


def _start_decoder_watch(kind, path, parser, default_mode):
    if not path:
        return
    _decoder_status["files"][kind] = path
    from_end = tail_from_end_default()

    async def handle_line(line):
        parsed = parser(line)
        payload = parsed or {"raw": str(line).strip(), "mode": default_mode}
        event = build_callsign_event(payload, _scan_state)
        if not event:
            return
        _touch_decoder_source(event.get("source"))
        _db.insert_callsign(event)

    task = asyncio.create_task(
        tail_lines(path, handle_line, _decoder_stop, poll_s=1.0, from_end=from_end)
    )
    _decoder_tasks.append(task)
    _log(f"decoder_watch_started {kind} {path}")


@app.on_event("startup")
async def on_startup():
    _decoder_stop.clear()
    _start_decoder_watch("wsjtx", os.getenv("WSJTX_ALLTXT_PATH"), parse_wsjtx_line, "FT8")
    _start_decoder_watch("aprs", os.getenv("DIREWOLF_LOG_PATH"), parse_aprs_line, "APRS")
    _start_decoder_watch("cw", os.getenv("CW_DECODE_PATH"), parse_cw_text, "CW")
    listener = create_wsjtx_udp_listener(_wsjtx_state, _handle_wsjtx_udp, logger=_log)
    if listener:
        transport, _ = await listener
        global _wsjtx_transport
        _wsjtx_transport = transport
        listen_addr = describe_wsjtx_udp()
        _decoder_status["wsjtx_udp"].update({"enabled": True, "listen": listen_addr})
        _log(f"wsjtx_udp_listen {listen_addr}")
    global _kiss_task
    _kiss_task = asyncio.create_task(
        kiss_loop(_handle_kiss_event, _decoder_stop, logger=_log, status_cb=_handle_kiss_status)
    )
    kiss_addr = describe_kiss()
    if kiss_addr:
        _decoder_status["direwolf_kiss"].update({"enabled": True, "address": kiss_addr})
        _log(f"direwolf_kiss_listen {kiss_addr}")


@app.on_event("shutdown")
async def on_shutdown():
    _decoder_stop.set()
    for task in _decoder_tasks:
        task.cancel()
    _decoder_tasks.clear()
    if _wsjtx_transport:
        _wsjtx_transport.close()
    if _kiss_task:
        _kiss_task.cancel()


@app.get("/api/health")
def health(request: Request):
    _enforce_auth(request)
    return {
        "status": "ok",
        "version": "0.1.0",
        "devices": len(_controller.list_devices())
    }


@app.get("/api/devices")
def devices(request: Request):
    _enforce_auth(request)
    return _controller.list_devices()


@app.get("/api/bands")
def bands(request: Request):
    _enforce_auth(request)
    return _db.get_bands()


@app.post("/api/bands")
def save_band(payload: dict, request: Request):
    _enforce_auth(request)
    band = payload.get("band", {})
    start_hz = int(band.get("start_hz", 0))
    end_hz = int(band.get("end_hz", 0))
    if start_hz <= 0 or end_hz <= 0 or start_hz >= end_hz:
        raise HTTPException(status_code=400, detail="Invalid band range")
    _db.upsert_band(band)
    return {"status": "ok"}


@app.post("/api/scan/start")
async def scan_start(payload: dict, request: Request):
    _enforce_auth(request)
    try:
        normalized_payload = load_scan_request(payload)
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scan = normalized_payload.get("scan", {})
    region_profile_path = normalized_payload.get("region_profile_path")
    if region_profile_path:
        try:
            region_profile = load_region_profile(region_profile_path)
            apply_region_profile_to_scan(scan, region_profile)
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if scan.get("band"):
        start_hz = int(scan.get("start_hz", 0) or 0)
        end_hz = int(scan.get("end_hz", 0) or 0)
        if start_hz <= 0 or end_hz <= 0:
            for band in _db.get_bands():
                if str(band.get("name", "")).lower() == str(scan.get("band", "")).lower():
                    if start_hz <= 0:
                        scan["start_hz"] = band.get("start_hz")
                    if end_hz <= 0:
                        scan["end_hz"] = band.get("end_hz")
                    break
    await _scan_engine.start_async(scan)
    _scan_state["state"] = "running"
    _scan_state["device"] = normalized_payload.get("device", "rtl_sdr")
    _scan_state["started_at"] = datetime.now(timezone.utc).isoformat()
    _scan_state["scan"] = scan
    _scan_state["scan_id"] = _db.start_scan(scan, _scan_state["started_at"])
    _log("scan_start")
    return _scan_state


@app.post("/api/scan/stop")
async def scan_stop(request: Request):
    _enforce_auth(request)
    await _scan_engine.stop_async()
    _scan_state["state"] = "stopped"
    _db.end_scan(_scan_state.get("scan_id"), datetime.now(timezone.utc).isoformat())
    _log("scan_stop")
    return _scan_state


@app.get("/api/events")
def events(
    limit: int = 1000,
    offset: int = 0,
    band: str | None = None,
    mode: str | None = None,
    callsign: str | None = None,
    start: str | None = None,
    end: str | None = None,
    format: str | None = None,
    request: Request = None
):
    if request:
        _enforce_auth(request)
    settings = _db.get_settings()
    modes = settings.get("modes") or {}
    if mode is None and modes:
        enabled_modes = [
            name.upper()
            for name, enabled in modes.items()
            if enabled
        ]
        if enabled_modes:
            mode = enabled_modes[0]
    data = _db.get_events(limit=limit, offset=offset, band=band, mode=mode, callsign=callsign, start=start, end=end)
    if format == "csv":
        lines = ["Type,Timestamp,Band,FrequencyHz,Mode,Callsign,Confidence,SNR,PowerDbm,ScanId"]
        for item in data:
            lines.append(",".join([
                str(item.get("type", "")),
                str(item.get("timestamp", "")),
                str(item.get("band", "")),
                str(item.get("frequency_hz", "")),
                str(item.get("mode", "")),
                str(item.get("callsign", "")),
                str(item.get("confidence", "")),
                str(item.get("snr_db", "")),
                str(item.get("power_dbm", "")),
                str(item.get("scan_id", ""))
            ]))
        return PlainTextResponse("\n".join(lines), media_type="text/csv")
    return data


@app.get("/api/events/count")
def events_count(
    band: str | None = None,
    mode: str | None = None,
    callsign: str | None = None,
    start: str | None = None,
    end: str | None = None,
    request: Request = None
):
    if request:
        _enforce_auth(request)
    cache_key = (band, mode, callsign, start, end)
    now = time.time()
    if _count_cache["key"] == cache_key and (now - _count_cache["timestamp"]) < 5:
        return {"total": _count_cache["value"]}
    total = _db.count_events(band=band, mode=mode, callsign=callsign, start=start, end=end)
    _count_cache.update({"timestamp": now, "value": total, "key": cache_key})
    return {"total": total}


@app.get("/api/events/stats")
def events_stats(request: Request = None):
    if request:
        _enforce_auth(request)
    return {"modes": _db.get_event_stats()}


@app.get("/api/decoders/status")
def decoder_status(request: Request = None):
    if request:
        _enforce_auth(request)
    return {
        "ingest": {
            "endpoint": "/api/decoders/events",
            "batch": True
        },
        "supported_modes": ["FT8", "FT4", "APRS", "CW", "SSB", "Unknown"],
        "sources": ["wsjtx", "direwolf", "cw", "asr", "dsp"],
        "status": _decoder_status
    }


@app.post("/api/decoders/events")
def decoder_events(payload: dict, request: Request = None):
    if request:
        _enforce_auth(request)
    items = payload.get("events")
    if items is None:
        items = [payload.get("event", payload)]
    return _ingest_callsign_payloads(items, payload)


@app.post("/api/decoders/wsjtx")
def decoder_wsjtx(payload: dict, request: Request = None):
    if request:
        _enforce_auth(request)
    lines = payload.get("lines")
    if lines is None:
        lines = [payload.get("line", "")]
    events = []
    for line in lines:
        parsed = parse_wsjtx_line(line)
        if parsed:
            events.append(parsed)
        else:
            events.append({"raw": str(line).strip(), "mode": "FT8"})
    return _ingest_callsign_payloads(events, payload)


@app.post("/api/decoders/aprs")
def decoder_aprs(payload: dict, request: Request = None):
    if request:
        _enforce_auth(request)
    lines = payload.get("lines")
    if lines is None:
        lines = [payload.get("line", "")]
    events = []
    for line in lines:
        parsed = parse_aprs_line(line)
        if parsed:
            events.append(parsed)
        else:
            events.append({"raw": str(line).strip(), "mode": "APRS"})
    return _ingest_callsign_payloads(events, payload)


@app.post("/api/decoders/cw")
def decoder_cw(payload: dict, request: Request = None):
    if request:
        _enforce_auth(request)
    texts = payload.get("texts")
    if texts is None:
        texts = [payload.get("text", "")]
    events = []
    for text in texts:
        parsed = parse_cw_text(text)
        if parsed:
            events.append(parsed)
        else:
            events.append({"raw": str(text).strip(), "mode": "CW"})
    return _ingest_callsign_payloads(events, payload)


def _ingest_callsign_payloads(items, defaults):
    saved = 0
    errors = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append({"index": idx, "error": "invalid_event"})
            continue
        payload = dict(defaults)
        payload.update(item)
        event = build_callsign_event(payload, _scan_state)
        if not event:
            errors.append({"index": idx, "error": "invalid_event"})
            continue
        _touch_decoder_source(event.get("source"))
        _db.insert_callsign(event)
        saved += 1
    return {"status": "ok", "saved": saved, "errors": errors}


def _handle_wsjtx_udp(payload):
    _decoder_status["wsjtx_udp"]["last_packet_at"] = datetime.now(timezone.utc).isoformat()
    return _ingest_callsign_payloads([payload], {})


def _handle_kiss_event(payload):
    _decoder_status["direwolf_kiss"]["last_packet_at"] = datetime.now(timezone.utc).isoformat()
    return _ingest_callsign_payloads([payload], {})


def _handle_kiss_status(event, detail):
    if event == "connected":
        _decoder_status["direwolf_kiss"]["connected"] = True
        _decoder_status["direwolf_kiss"]["last_error"] = None
    elif event == "disconnected":
        _decoder_status["direwolf_kiss"]["connected"] = False
    elif event == "error":
        _decoder_status["direwolf_kiss"]["last_error"] = detail


@app.get("/api/export")
def export_events(
    limit: int = 1000,
    offset: int = 0,
    band: str | None = None,
    mode: str | None = None,
    callsign: str | None = None,
    start: str | None = None,
    end: str | None = None,
    format: str = "csv",
    request: Request = None
):
    if request:
        _enforce_auth(request)
    return events(
        limit=limit,
        offset=offset,
        band=band,
        mode=mode,
        callsign=callsign,
        start=start,
        end=end,
        format=format
    )


@app.get("/api/scans")
def scans(limit: int = 100, request: Request = None):
    if request:
        _enforce_auth(request)
    return _db.get_scans(limit=limit)


@app.get("/api/logs")
def logs(limit: int = 200, request: Request = None):
    if request:
        _enforce_auth(request)
    return _logs[-limit:]


@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    if _auth_required() and not _verify_basic_auth(websocket.headers.get("authorization")):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    last_idx = 0
    while True:
        if last_idx < len(_logs):
            batch = _logs[last_idx:]
            last_idx = len(_logs)
            await websocket.send_json({"logs": batch})
        await asyncio.sleep(1.0)


@app.get("/api/scan/status")
def scan_status(request: Request = None):
    if request:
        _enforce_auth(request)
    payload = dict(_scan_state)
    payload["engine"] = _scan_engine.status()
    return payload


@app.get("/api/settings")
def get_settings(request: Request):
    _enforce_auth(request)
    settings = _db.get_settings()
    if "summary" not in settings:
        settings["summary"] = {"showBand": True, "showMode": True}
    return settings


@app.post("/api/settings")
def save_settings(payload: dict, request: Request):
    _enforce_auth(request)
    existing = _db.get_settings()
    if payload.get("band"):
        existing["band"] = payload.get("band")
    if payload.get("device_id"):
        existing["device_id"] = payload.get("device_id")
    if payload.get("auth_hint"):
        existing["auth_hint"] = payload.get("auth_hint")
    if payload.get("bands"):
        existing["bands"] = payload.get("bands")
    if payload.get("favorites"):
        existing["favorites"] = payload.get("favorites")
    if payload.get("modes"):
        existing["modes"] = payload.get("modes")
    if payload.get("summary"):
        existing["summary"] = payload.get("summary")
    _db.save_settings(existing)
    return {"status": "ok"}


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    if _auth_required() and not _verify_basic_auth(websocket.headers.get("authorization")):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    while True:
        iq = _scan_engine.read_iq(2048)
        if iq is None:
            iq = (np.random.randn(2048) + 1j * np.random.randn(2048)) * 0.02
        if _agc_enabled:
            iq, gain_db = apply_agc_smoothed(
                iq,
                _agc_state,
                target_rms=_agc_target_rms,
                max_gain_db=_agc_max_gain_db,
                alpha=_agc_alpha
            )
            global _last_agc_gain_db
            _last_agc_gain_db = gain_db
        band = _scan_engine.config.get("band") if _scan_engine.config else None
        power_db = compute_power_db(iq)
        noise_floor = _update_noise_floor(band, power_db)
        threshold_dbm = noise_floor + 6.0
        occupancy = estimate_occupancy(
            iq,
            _scan_engine.sample_rate,
            threshold_dbm=threshold_dbm,
            adapt=False,
            snr_threshold_db=_snr_threshold_db,
            min_bw_hz=_min_bw_hz
        )
        if occupancy:
            best = max(occupancy, key=lambda item: item.get("snr_db", 0.0))
            nf_db = best.get("noise_floor_db")
            if nf_db is not None:
                _update_noise_floor(band, nf_db)
            offset_hz = best.get("offset_hz")
            frequency_hz = _scan_engine.center_hz
            if offset_hz is not None:
                frequency_hz = int(_scan_engine.center_hz + offset_hz)
            adaptive_threshold = _update_threshold(band, best.get("threshold_dbm"))
            event = {
                "type": "occupancy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "band": band,
                "frequency_hz": frequency_hz,
                "offset_hz": offset_hz,
                "bandwidth_hz": best["bandwidth_hz"],
                "power_dbm": power_db,
                "snr_db": best.get("snr_db"),
                "threshold_dbm": adaptive_threshold or best.get("threshold_dbm", threshold_dbm),
                "occupied": best["occupied"],
                "mode": "Unknown",
                "confidence": 0.4,
                "device": _scan_state.get("device"),
                "scan_id": _scan_state.get("scan_id")
            }
            settings = _db.get_settings()
            modes = settings.get("modes") or {}
            mode_key = str(event.get("mode", "")).lower()
            if mode_key == "unknown":
                mode_key = "ssb"
            if modes and mode_key in modes and not modes.get(mode_key, True):
                await asyncio.sleep(1.0)
                continue
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
    if _auth_required() and not _verify_basic_auth(websocket.headers.get("authorization")):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    while True:
        frame_start = time.time()
        iq = _scan_engine.read_iq(2048)
        if iq is None:
            iq = (np.random.randn(2048) + 1j * np.random.randn(2048)) * 0.02
        agc_gain_db = None
        if _agc_enabled:
            iq, agc_gain_db = apply_agc_smoothed(
                iq,
                _agc_state,
                target_rms=_agc_target_rms,
                max_gain_db=_agc_max_gain_db,
                alpha=_agc_alpha
            )
            global _last_agc_gain_db
            _last_agc_gain_db = agc_gain_db
        fft_db, bin_hz, min_db, max_db = compute_fft_db(iq, _scan_engine.sample_rate, smooth_bins=6)
        peaks = detect_peaks(fft_db, bin_hz)
        noise_floor_db = estimate_noise_floor(fft_db)
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
                "max_db": max_db,
                "noise_floor_db": noise_floor_db,
                "peaks": peaks,
                "agc_gain_db": agc_gain_db
            }
        }
        await websocket.send_json(payload)
        global _last_send_ts
        _last_send_ts = time.time()
        await asyncio.sleep(0.2)


@app.websocket("/ws/status")
async def ws_status(websocket: WebSocket):
    if _auth_required() and not _verify_basic_auth(websocket.headers.get("authorization")):
        await websocket.close(code=1008)
        return
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
                "noise_floor_db": _noise_floor.get(band),
                "threshold_db": _threshold_state.get(band),
                "agc_gain_db": _last_agc_gain_db,
                "scan": _scan_engine.status()
            }
        }
        await websocket.send_json(payload)
        await asyncio.sleep(1.0)
