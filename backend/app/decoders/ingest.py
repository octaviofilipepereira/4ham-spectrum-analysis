# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 16:27:19 UTC

from datetime import datetime, timezone
import json
import re


_ALLOWED_MODES = {"FT8", "FT4", "WSPR", "APRS", "CW", "SSB", "Unknown"}
_BAND_RANGES = [
    ("160m", 1800000, 2000000),
    ("80m", 3500000, 4000000),
    ("60m", 5250000, 5450000),
    ("40m", 7000000, 7300000),
    ("30m", 10100000, 10150000),
    ("20m", 14000000, 14350000),
    ("17m", 18068000, 18168000),
    ("15m", 21000000, 21450000),
    ("12m", 24890000, 24990000),
    ("10m", 28000000, 29700000),
    ("6m", 50000000, 54000000),
    ("2m", 144000000, 148000000),
    ("70cm", 430000000, 440000000),
]


def _normalize_mode(value):
    if not value:
        return "Unknown"
    mode = str(value).upper()
    return mode if mode in _ALLOWED_MODES else "Unknown"


def _infer_source(mode):
    if mode in ("FT8", "FT4", "WSPR"):
        return "external_ft"
    if mode == "APRS":
        return "direwolf"
    if mode == "CW":
        return "cw"
    if mode == "SSB":
        return "asr"
    return "dsp"


def normalize_callsign(value):
    if not value:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9/]", "", str(value).upper())
    return cleaned or None


def _infer_band_from_frequency(frequency_hz):
    try:
        value = int(frequency_hz)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    for band, start_hz, end_hz in _BAND_RANGES:
        if start_hz <= value <= end_hz:
            return band
    return None


def build_callsign_event(payload, scan_state):
    if not isinstance(payload, dict):
        return None
    callsign = normalize_callsign(payload.get("callsign"))
    mode = _normalize_mode(payload.get("mode"))
    if not callsign:
        # For CW, allow events without an identified callsign so that decoded
        # text and occupancy data are still recorded (callsign stored as "").
        if mode == "CW" and payload.get("msg"):
            callsign = ""
        else:
            return None
    frequency_hz = payload.get("frequency_hz")
    if frequency_hz is None:
        frequency_hz = 0
    try:
        frequency_hz = int(frequency_hz)
    except (TypeError, ValueError):
        frequency_hz = 0
    band = payload.get("band") or _infer_band_from_frequency(frequency_hz)

    # Merge CW occupancy/decode fields into the payload JSON blob so they are
    # persisted without needing new DB columns and are available to the API.
    _extra = {}
    for _key in ("occupancy_rms", "occupancy_peak", "wpm"):
        _val = payload.get(_key)
        if _val is not None:
            _extra[_key] = _val
    _base = payload.get("payload")
    if _extra:
        try:
            _merged = {**(json.loads(_base) if isinstance(_base, str) else (_base or {})), **_extra}
            payload_blob = json.dumps(_merged)
        except Exception:
            payload_blob = json.dumps(_extra)
    else:
        payload_blob = _base

    return {
        "type": "callsign",
        "timestamp": payload.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "band": band,
        "frequency_hz": frequency_hz,
        "mode": mode,
        "callsign": callsign,
        "snr_db": payload.get("snr_db"),
        "df_hz": payload.get("df_hz"),
        "confidence": payload.get("confidence"),
        "raw": payload.get("raw"),
        "grid": payload.get("grid"),
        "report": payload.get("report"),
        "time_s": payload.get("time_s"),
        "dt_s": payload.get("dt_s"),
        "is_new": payload.get("is_new"),
        "path": payload.get("path"),
        "lat": payload.get("lat"),
        "lon": payload.get("lon"),
        "msg": payload.get("msg"),
        "payload": payload_blob,
        "source": payload.get("source") or _infer_source(mode),
        "device": payload.get("device") or scan_state.get("device"),
        "scan_id": payload.get("scan_id") or scan_state.get("scan_id")
    }
