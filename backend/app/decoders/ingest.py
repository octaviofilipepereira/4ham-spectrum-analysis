from datetime import datetime, timezone
import re


_ALLOWED_MODES = {"FT8", "FT4", "APRS", "CW", "SSB", "Unknown"}


def _normalize_mode(value):
    if not value:
        return "Unknown"
    mode = str(value).upper()
    return mode if mode in _ALLOWED_MODES else "Unknown"


def _infer_source(mode):
    if mode in ("FT8", "FT4"):
        return "wsjtx"
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


def build_callsign_event(payload, scan_state):
    if not isinstance(payload, dict):
        return None
    callsign = normalize_callsign(payload.get("callsign"))
    if not callsign:
        return None

    mode = _normalize_mode(payload.get("mode"))
    frequency_hz = payload.get("frequency_hz")
    if frequency_hz is None:
        frequency_hz = 0

    return {
        "type": "callsign",
        "timestamp": payload.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "band": payload.get("band"),
        "frequency_hz": int(frequency_hz),
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
        "payload": payload.get("payload"),
        "lat": payload.get("lat"),
        "lon": payload.get("lon"),
        "msg": payload.get("msg"),
        "source": payload.get("source") or _infer_source(mode),
        "device": payload.get("device") or scan_state.get("device"),
        "scan_id": payload.get("scan_id") or scan_state.get("scan_id")
    }
