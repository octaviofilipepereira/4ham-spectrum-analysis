import asyncio
import os
import time
import base64
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from fastapi import FastAPI, WebSocket, Request, HTTPException, status
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.config.loader import (
    ConfigError,
    apply_region_profile_to_scan,
    load_region_profile,
    load_scan_request,
)
from app.decoders.ingest import build_callsign_event
from app.decoders.parsers import parse_wsjtx_line, parse_aprs_line, parse_cw_text, parse_ssb_asr_text
from app.decoders.watchers import tail_lines, tail_from_end_default
from app.decoders.wsjtx_udp import WsjtxState, create_wsjtx_udp_listener, describe_wsjtx_udp
from app.decoders.launchers import env_flag, resolve_command, start_process, stop_process
from app.decoders.direwolf_kiss import kiss_loop, describe_kiss
from app.dsp.pipeline import (
    compute_fft_db,
    compute_power_db,
    estimate_occupancy,
    detect_peaks,
    estimate_noise_floor,
    apply_agc_smoothed,
    classify_mode_heuristic
)
from app.scan.engine import ScanEngine
from app.sdr.controller import SDRController, soapy_import_status
from app.streaming import encode_delta_int8
from app.storage.db import Database
from app.storage.exporter import ExportManager

app = FastAPI(title="4ham Spectrum Analysis")

_controller = SDRController()
_scan_engine = ScanEngine(_controller)
os.makedirs("data", exist_ok=True)
_db = Database("data/events.sqlite")
_export_manager = None
_scan_state = {
    "state": "stopped",
    "device": None,
    "started_at": None,
    "scan": None,
    "scan_id": None
}
_default_modes = {
    "ft8": False,
    "aprs": False,
    "cw": False,
    "ssb": True,
}


def _default_settings_payload():
    return {
        "modes": dict(_default_modes),
        "summary": {"showBand": True, "showMode": True},
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
_wsjtx_process = None
_kiss_task = None
_direwolf_process = None
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


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return bool(default)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


_agc_enabled = os.getenv("DSP_AGC_ENABLE", "0").lower() in {"1", "true", "yes", "on"}
_agc_target_rms = _env_float("DSP_AGC_TARGET_RMS", 0.25)
_agc_max_gain_db = _env_float("DSP_AGC_MAX_GAIN_DB", 30.0)
_agc_alpha = _env_float("DSP_AGC_ALPHA", 0.2)
_snr_threshold_db = _env_float("DSP_SNR_THRESHOLD_DB", 6.0)
_min_bw_hz = _env_int("DSP_MIN_BW_HZ", 500)
_ws_spectrum_fps = max(1.0, _env_float("WS_SPECTRUM_FPS", 5.0))
_ws_send_timeout_s = max(0.01, _env_float("WS_SEND_TIMEOUT_S", 0.1))
_ws_compress_spectrum = _env_bool("WS_COMPRESS_SPECTRUM", True)
_ws_protocol_version = "1.1"
_export_manager = ExportManager(
    export_dir="data/exports",
    db=_db,
    max_files=_env_int("EXPORT_MAX_FILES", 50),
    max_age_days=_env_int("EXPORT_MAX_AGE_DAYS", 7),
)
_agc_state = {}
_last_agc_gain_db = None
_spectrum_send_stats = {"sent": 0, "dropped": 0}
_decoder_status = {
    "sources": {},
    "wsjtx_udp": {
        "enabled": False,
        "listen": None,
        "last_packet_at": None,
        "autostart": False,
        "process_running": False,
        "process_pid": None,
        "last_error": None
    },
    "direwolf_kiss": {
        "enabled": False,
        "address": None,
        "connected": False,
        "last_packet_at": None,
        "last_error": None,
        "autostart": False,
        "process_running": False,
        "process_pid": None
    },
    "files": {
        "wsjtx": None,
        "aprs": None,
        "cw": None,
        "ssb": None
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


def _command_exists(command):
    return shutil.which(command) is not None


def _run_command(command, timeout=180):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "command": " ".join(command),
            "returncode": result.returncode,
            "stdout": (result.stdout or "")[-4000:],
            "stderr": (result.stderr or "")[-4000:],
        }
    except Exception as exc:
        return {
            "command": " ".join(command),
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
        }


def _is_apt_package_installed(package_name):
    result = _run_command(["dpkg-query", "-W", "-f=${Status}", package_name], timeout=30)
    if result.get("returncode") != 0:
        return False
    status_text = (result.get("stdout") or "").strip().lower()
    return "install ok installed" in status_text


def _check_apt_packages(packages):
    installed = []
    missing = []
    for package_name in packages:
        if _is_apt_package_installed(package_name):
            installed.append(package_name)
        else:
            missing.append(package_name)
    return {"installed": installed, "missing": missing}


def _list_audio_devices_from_pactl(kind):
    result = _run_command(["pactl", "list", "short", kind], timeout=15)
    if result.get("returncode") != 0:
        return []
    devices = []
    for line in (result.get("stdout") or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1].strip():
            devices.append(parts[1].strip())
    return devices


def _parse_default_pactl_endpoint(info_text, label):
    for line in (info_text or "").splitlines():
        if line.startswith(label):
            return line.split(":", 1)[1].strip()
    return None


def _list_audio_devices_from_alsa(command):
    result = _run_command([command, "-L"], timeout=15)
    if result.get("returncode") != 0:
        return []
    devices = []
    for line in (result.get("stdout") or "").splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        if line[:1].isspace() or line.startswith("\t"):
            continue
        devices.append(item)
    return devices


def _probe_audio_setup():
    inputs = []
    outputs = []
    default_input = None
    default_output = None
    methods = []

    if _command_exists("pactl"):
        methods.append("pactl")
        info = _run_command(["pactl", "info"], timeout=15)
        info_text = info.get("stdout") or ""
        default_input = _parse_default_pactl_endpoint(info_text, "Default Source")
        default_output = _parse_default_pactl_endpoint(info_text, "Default Sink")
        inputs = _list_audio_devices_from_pactl("sources")
        outputs = _list_audio_devices_from_pactl("sinks")

    if not inputs and _command_exists("arecord"):
        methods.append("arecord")
        inputs = _list_audio_devices_from_alsa("arecord")
    if not outputs and _command_exists("aplay"):
        methods.append("aplay")
        outputs = _list_audio_devices_from_alsa("aplay")

    suggested = {
        "input_device": default_input or (inputs[0] if inputs else ""),
        "output_device": default_output or (outputs[0] if outputs else ""),
        "sample_rate": 48000,
        "rx_gain": 1,
        "tx_gain": 1,
    }
    return {
        "methods": methods,
        "inputs": inputs,
        "outputs": outputs,
        "default_input": default_input,
        "default_output": default_output,
        "suggested": suggested,
    }


def _normalize_device_choice(choice):
    value = str(choice or "").strip().lower()
    if "rtl" in value:
        return "rtl"
    if "hack" in value:
        return "hackrf"
    if "air" in value:
        return "airspy"
    if not value:
        return "other"
    return value


def _find_device_by_choice(devices, choice):
    term = str(choice or "").lower()
    for item in devices:
        haystack = " ".join([
            str(item.get("id", "")).lower(),
            str(item.get("type", "")).lower(),
            str(item.get("name", "")).lower(),
        ])
        if term in haystack:
            return item
    return None


def _device_profile(choice):
    profiles = {
        "rtl": {
            "sample_rate": 2048000,
            "gain": 30,
            "ppm_correction": 0,
            "frequency_offset_hz": 0,
            "gain_profile": "auto",
        },
        "hackrf": {
            "sample_rate": 2000000,
            "gain": 20,
            "ppm_correction": 0,
            "frequency_offset_hz": 0,
            "gain_profile": "auto",
        },
        "airspy": {
            "sample_rate": 2500000,
            "gain": 20,
            "ppm_correction": 0,
            "frequency_offset_hz": 0,
            "gain_profile": "auto",
        },
        "other": {
            "sample_rate": 48000,
            "gain": 20,
            "ppm_correction": 0,
            "frequency_offset_hz": 0,
            "gain_profile": "auto",
        },
    }
    return profiles.get(choice, profiles["other"])


def _device_requirements(choice):
    linux_packages = ["python3-soapysdr", "soapysdr-tools", "libsoapysdr-dev"]
    if choice == "rtl":
        linux_packages.extend(["soapysdr-module-rtlsdr", "rtl-sdr"])
    elif choice == "hackrf":
        linux_packages.extend(["soapysdr-module-hackrf", "hackrf"])
    elif choice == "airspy":
        linux_packages.extend(["soapysdr-module-airspy", "airspy"])
    else:
        linux_packages.append("soapysdr-module-all")
    return {
        "python_modules": ["SoapySDR"],
        "linux_apt_packages": linux_packages,
        "required_commands": ["SoapySDRUtil", "rtl_test", "lsusb"],
    }


def _probe_device_setup(choice):
    devices = _controller.list_devices()
    matched = _find_device_by_choice(devices, choice)
    soapy_import, soapy_error = soapy_import_status()

    requirements = _device_requirements(choice)
    apt_status = {"installed": [], "missing": []}
    if sys.platform.startswith("linux"):
        apt_status = _check_apt_packages(requirements.get("linux_apt_packages", []))

    return {
        "platform": sys.platform,
        "commands": {
            "SoapySDRUtil": _command_exists("SoapySDRUtil"),
            "rtl_test": _command_exists("rtl_test"),
            "lsusb": _command_exists("lsusb"),
        },
        "python": {
            "soapy_import_ok": soapy_import,
            "soapy_import_error": soapy_error,
        },
        "apt_packages": apt_status,
        "devices_detected": devices,
        "match_found": bool(matched),
        "matched_device": matched,
    }


def _run_linux_auto_install(choice, missing_packages=None):
    attempted = False
    steps = []

    if not sys.platform.startswith("linux"):
        return {
            "attempted": False,
            "success": False,
            "error": "auto_install_only_supported_on_linux",
            "method": None,
            "steps": steps,
        }

    base_packages = list(missing_packages or [])
    if not base_packages:
        return {
            "attempted": False,
            "success": True,
            "error": None,
            "method": None,
            "steps": steps,
        }

    strategies = []
    if _command_exists("apt-get") and hasattr(os, "geteuid") and os.geteuid() == 0:
        strategies.append({
            "name": "root_direct",
            "commands": [
                ["apt-get", "update"],
                ["apt-get", "install", "-y", *base_packages],
            ],
        })
    if _command_exists("sudo"):
        strategies.append({
            "name": "sudo_nopasswd",
            "commands": [
                ["sudo", "-n", "apt-get", "update"],
                ["sudo", "-n", "apt-get", "install", "-y", *base_packages],
            ],
        })
    if _command_exists("pkexec"):
        strategies.append({
            "name": "pkexec_gui",
            "commands": [
                ["pkexec", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "update"],
                ["pkexec", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", *base_packages],
            ],
        })

    if not strategies:
        return {
            "attempted": False,
            "success": False,
            "error": "no_privilege_escalation_tool",
            "method": None,
            "steps": steps,
        }

    for strategy in strategies:
        strategy_ok = True
        for command in strategy["commands"]:
            attempted = True
            result = _run_command(command, timeout=900)
            result["strategy"] = strategy["name"]
            steps.append(result)
            if result.get("returncode") != 0:
                strategy_ok = False
                break
        if strategy_ok:
            return {
                "attempted": attempted,
                "success": True,
                "error": None,
                "method": strategy["name"],
                "steps": steps,
            }

    combined_stderr = "\n".join((item.get("stderr") or "") for item in steps).lower()
    needs_elevation = any(token in combined_stderr for token in [
        "password is required",
        "authentication",
        "polkit",
        "not authorized",
        "not allowed",
        "permission denied",
    ])

    return {
        "attempted": attempted,
        "success": False,
        "error": "elevation_required" if needs_elevation else "apt_install_failed",
        "method": None,
        "steps": steps,
    }


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


async def _maybe_autostart_decoder_process(kind, enabled, flag_env, cmd_env, default_command, status_key):
    if not enabled and not env_flag(flag_env, default=False):
        return None

    command = resolve_command(cmd_env, default_command)
    _decoder_status[status_key]["autostart"] = True
    if not command:
        _decoder_status[status_key]["last_error"] = f"{kind}_autostart_missing_command"
        return None

    try:
        process = await start_process(command)
    except Exception as exc:
        _decoder_status[status_key]["last_error"] = f"{kind}_autostart_failed {exc}"
        _log(f"{kind}_autostart_failed {exc}")
        return None

    _decoder_status[status_key]["process_running"] = bool(process and process.returncode is None)
    _decoder_status[status_key]["process_pid"] = process.pid if process else None
    _decoder_status[status_key]["last_error"] = None
    _log(f"{kind}_autostart_ok pid={process.pid if process else 'na'}")
    return process


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
    _start_decoder_watch("ssb", os.getenv("SSB_ASR_PATH"), parse_ssb_asr_text, "SSB")
    listener = create_wsjtx_udp_listener(_wsjtx_state, _handle_wsjtx_udp, logger=_log)
    if listener:
        transport, _ = await listener
        global _wsjtx_transport
        _wsjtx_transport = transport
        listen_addr = describe_wsjtx_udp()
        _decoder_status["wsjtx_udp"].update({"enabled": True, "listen": listen_addr})
        _log(f"wsjtx_udp_listen {listen_addr}")
    global _wsjtx_process
    _wsjtx_process = await _maybe_autostart_decoder_process(
        kind="wsjtx",
        enabled=bool(describe_wsjtx_udp()),
        flag_env="WSJTX_AUTOSTART",
        cmd_env="WSJTX_CMD",
        default_command="wsjtx",
        status_key="wsjtx_udp"
    )
    global _kiss_task
    _kiss_task = asyncio.create_task(
        kiss_loop(_handle_kiss_event, _decoder_stop, logger=_log, status_cb=_handle_kiss_status)
    )
    kiss_addr = describe_kiss()
    if kiss_addr:
        _decoder_status["direwolf_kiss"].update({"enabled": True, "address": kiss_addr})
        _log(f"direwolf_kiss_listen {kiss_addr}")
    global _direwolf_process
    _direwolf_process = await _maybe_autostart_decoder_process(
        kind="direwolf",
        enabled=bool(kiss_addr),
        flag_env="DIREWOLF_AUTOSTART",
        cmd_env="DIREWOLF_CMD",
        default_command="direwolf -t 0 -p",
        status_key="direwolf_kiss"
    )


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
    if _wsjtx_process:
        await stop_process(_wsjtx_process)
    if _direwolf_process:
        await stop_process(_direwolf_process)


@app.get("/api/health")
def health(request: Request):
    _enforce_auth(request)
    return {
        "status": "ok",
        "version": "0.2.0",
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
    selected_device = normalized_payload.get("device")
    if selected_device and not scan.get("device_id"):
        scan["device_id"] = selected_device
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


@app.post("/api/decoders/ssb")
def decoder_ssb(payload: dict, request: Request = None):
    if request:
        _enforce_auth(request)
    texts = payload.get("texts")
    if texts is None:
        texts = [payload.get("text", "")]
    events = []
    for text in texts:
        parsed = parse_ssb_asr_text(text)
        if parsed:
            events.append(parsed)
        else:
            events.append({"raw": str(text).strip(), "mode": "SSB"})
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
        if payload.get("frequency_hz") in (None, 0, "0", ""):
            center_hz = _scan_engine.center_hz or _spectrum_cache.get("center_hz")
            if center_hz:
                payload["frequency_hz"] = int(center_hz)
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


def _refresh_decoder_process_status():
    if _wsjtx_process:
        _decoder_status["wsjtx_udp"]["process_running"] = _wsjtx_process.returncode is None
        _decoder_status["wsjtx_udp"]["process_pid"] = _wsjtx_process.pid
    if _direwolf_process:
        _decoder_status["direwolf_kiss"]["process_running"] = _direwolf_process.returncode is None
        _decoder_status["direwolf_kiss"]["process_pid"] = _direwolf_process.pid


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


@app.post("/api/exports")
def create_export(payload: dict, request: Request = None):
    if request:
        _enforce_auth(request)
    payload = payload or {}
    format_name = str(payload.get("format", "csv")).lower()
    if format_name not in {"csv", "json"}:
        raise HTTPException(status_code=400, detail="Unsupported export format")

    data = _db.get_events(
        limit=int(payload.get("limit", 1000)),
        offset=int(payload.get("offset", 0)),
        band=payload.get("band"),
        mode=payload.get("mode"),
        callsign=payload.get("callsign"),
        start=payload.get("start"),
        end=payload.get("end"),
    )
    item = _export_manager.create_export(data, format_name=format_name)
    return {
        "status": "ok",
        "export": {
            **item,
            "download_url": f"/api/exports/{item['id']}"
        }
    }


@app.get("/api/exports")
def list_exports(limit: int = 100, request: Request = None):
    if request:
        _enforce_auth(request)
    items = _export_manager.list_exports(limit=limit)
    return {
        "items": [
            {
                **item,
                "download_url": f"/api/exports/{item['id']}"
            }
            for item in items
        ]
    }


@app.get("/api/exports/{export_id}")
def download_export(export_id: str, request: Request = None):
    if request:
        _enforce_auth(request)
    item = _export_manager.get_export(export_id)
    if not item:
        raise HTTPException(status_code=404, detail="Export not found")
    path = item.get("path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Export file missing")
    media = "application/json" if item.get("format") == "json" else "text/csv"
    return FileResponse(path, media_type=media, filename=os.path.basename(path))


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
    modes = settings.get("modes") or {}
    settings["modes"] = {
        "ft8": bool(modes.get("ft8", _default_modes["ft8"])),
        "aprs": bool(modes.get("aprs", _default_modes["aprs"])),
        "cw": bool(modes.get("cw", _default_modes["cw"])),
        "ssb": bool(modes.get("ssb", _default_modes["ssb"])),
    }
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
        modes = payload.get("modes") or {}
        existing["modes"] = {
            "ft8": bool(modes.get("ft8", _default_modes["ft8"])),
            "aprs": bool(modes.get("aprs", _default_modes["aprs"])),
            "cw": bool(modes.get("cw", _default_modes["cw"])),
            "ssb": bool(modes.get("ssb", _default_modes["ssb"])),
        }
    if payload.get("summary"):
        existing["summary"] = payload.get("summary")
    if "station" in payload:
        existing["station"] = payload.get("station") or {}
    if "device_config" in payload:
        existing["device_config"] = payload.get("device_config") or {}
    if "audio_config" in payload:
        existing["audio_config"] = payload.get("audio_config") or {}
    _db.save_settings(existing)
    return {"status": "ok"}


@app.post("/api/settings/reset-defaults")
def reset_settings_defaults(request: Request):
    _enforce_auth(request)
    defaults = _default_settings_payload()
    _db.save_settings(defaults)
    return {"status": "ok", "settings": defaults}


@app.post("/api/admin/reset-all-config")
def admin_reset_all_config(request: Request):
    _enforce_auth(request)
    _db.clear_configuration()
    return {"status": "ok"}


@app.post("/api/admin/device/setup")
def admin_device_setup(payload: dict, request: Request):
    _enforce_auth(request)
    payload = payload or {}
    choice = _normalize_device_choice(payload.get("device_type"))
    dry_run = bool(payload.get("dry_run", False))
    auto_install = bool(payload.get("auto_install", False))
    apply_config = bool(payload.get("apply_config", True))
    requirements = _device_requirements(choice)

    probe_before = _probe_device_setup(choice)
    missing_packages_before = probe_before.get("apt_packages", {}).get("missing", [])
    install_result = {
        "attempted": False,
        "success": True,
        "error": None,
        "method": None,
        "steps": [],
    }

    should_install = bool(missing_packages_before)
    if not dry_run and auto_install and should_install:
        install_result = _run_linux_auto_install(choice, missing_packages=missing_packages_before)

    probe_after = _probe_device_setup(choice)
    matched = probe_after.get("matched_device")
    profile = _device_profile(choice)
    audio_probe = _probe_audio_setup()

    configured = {
        "applied": False,
        "device_id": None,
        "profile": profile,
        "device_config": None,
        "audio_config": audio_probe.get("suggested"),
    }
    if not dry_run and apply_config and matched:
        settings = _db.get_settings()
        settings["device_id"] = matched.get("id")
        device_config = settings.get("device_config") or {}
        device_config["device_class"] = choice if choice in {"rtl", "hackrf", "airspy"} else "auto"
        device_config["ppm_correction"] = profile.get("ppm_correction", 0)
        device_config["frequency_offset_hz"] = profile.get("frequency_offset_hz", 0)
        device_config["gain_profile"] = profile.get("gain_profile", "auto")
        settings["device_config"] = device_config
        settings["audio_config"] = audio_probe.get("suggested")
        _db.save_settings(settings)
        configured = {
            "applied": True,
            "device_id": matched.get("id"),
            "profile": profile,
            "device_config": device_config,
            "audio_config": audio_probe.get("suggested"),
        }

    return {
        "status": "ok",
        "device_type": choice,
        "dry_run": dry_run,
        "requirements": requirements,
        "missing_packages_before": missing_packages_before,
        "probe_before": probe_before,
        "install": install_result,
        "probe_after": probe_after,
        "audio_probe": audio_probe,
        "configured": configured,
    }


@app.post("/api/admin/config/test")
def admin_config_test(payload: dict, request: Request):
    _enforce_auth(request)
    payload = payload or {}

    selected_device_id = payload.get("device_id")
    audio_config = payload.get("audio_config") or {}

    devices = _controller.list_devices()
    soapy_ok, soapy_error = soapy_import_status()
    device_ok = bool(devices)
    if selected_device_id:
        device_ok = any(str(item.get("id")) == str(selected_device_id) for item in devices)

    sample_rate = int(audio_config.get("sample_rate") or 0)
    rx_gain = float(audio_config.get("rx_gain") or 0)
    tx_gain = float(audio_config.get("tx_gain") or 0)
    audio_checks = {
        "arecord": _command_exists("arecord"),
        "aplay": _command_exists("aplay"),
        "pactl": _command_exists("pactl"),
        "pw-cli": _command_exists("pw-cli"),
        "sample_rate_valid": 8000 <= sample_rate <= 384000,
        "rx_gain_valid": 0.0 <= rx_gain <= 10.0,
        "tx_gain_valid": 0.0 <= tx_gain <= 10.0,
    }
    audio_ok = bool(
        audio_checks["sample_rate_valid"]
        and audio_checks["rx_gain_valid"]
        and audio_checks["tx_gain_valid"]
        and (audio_checks["arecord"] or audio_checks["pactl"] or audio_checks["pw-cli"])
        and (audio_checks["aplay"] or audio_checks["pactl"] or audio_checks["pw-cli"])
    )

    return {
        "status": "ok",
        "device": {
            "selected": selected_device_id,
            "ok": device_ok and soapy_ok,
            "detected_count": len(devices),
            "soapy_import_ok": soapy_ok,
            "soapy_import_error": soapy_error,
        },
        "audio": {
            "ok": audio_ok,
            "checks": audio_checks,
        },
    }


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
            mode_name, mode_confidence = classify_mode_heuristic(
                best.get("bandwidth_hz"),
                best.get("snr_db")
            )
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
                "mode": mode_name,
                "confidence": mode_confidence,
                "device": _scan_state.get("device"),
                "scan_id": _scan_state.get("scan_id")
            }
            settings = _db.get_settings()
            modes = settings.get("modes") or {}
            mode_key = str(event.get("mode", "")).lower()
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
                "min_db": min_db,
                "max_db": max_db,
                "noise_floor_db": noise_floor_db,
                "peaks": peaks,
                "agc_gain_db": agc_gain_db
            }
        }

        if _ws_compress_spectrum:
            payload["spectrum_frame"].update(encode_delta_int8(fft_db))
        else:
            payload["spectrum_frame"]["fft_db"] = fft_db

        try:
            await asyncio.wait_for(websocket.send_json(payload), timeout=_ws_send_timeout_s)
            _spectrum_send_stats["sent"] += 1
        except asyncio.TimeoutError:
            _spectrum_send_stats["dropped"] += 1
            _log("ws_spectrum_drop send_timeout")

        global _last_send_ts
        _last_send_ts = time.time()
        elapsed = time.time() - frame_start
        period = 1.0 / _ws_spectrum_fps
        delay = max(0.0, period - elapsed)
        await asyncio.sleep(delay)


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
        sent = _spectrum_send_stats.get("sent", 0)
        dropped = _spectrum_send_stats.get("dropped", 0)
        total = sent + dropped
        drop_rate_pct = (float(dropped) / float(total) * 100.0) if total > 0 else 0.0
        payload = {
            "status": {
                "state": _scan_state.get("state"),
                "device": _scan_state.get("device"),
                "cpu_pct": _cpu_percent(),
                "frame_age_ms": frame_age_ms,
                "noise_floor_db": _noise_floor.get(band),
                "threshold_db": _threshold_state.get(band),
                "agc_gain_db": _last_agc_gain_db,
                "drop_rate_pct": round(drop_rate_pct, 2),
                "protocol_version": _ws_protocol_version,
                "scan": _scan_engine.status()
            }
        }
        await websocket.send_json(payload)
        await asyncio.sleep(1.0)


_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
