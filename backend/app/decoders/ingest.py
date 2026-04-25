# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 16:27:19 UTC

from datetime import datetime, timezone
import json
import re


_ALLOWED_MODES = {"FT8", "FT4", "WSPR", "APRS", "CW", "CW_CANDIDATE", "SSB", "SSB_TRAFFIC", "Unknown"}
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
    # EU SRD / ISM 33 cm band — LoRa-APRS default carrier (868.000 MHz).
    ("33cm", 863000000, 870000000),
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
    if mode in ("CW", "CW_CANDIDATE"):
        return "cw"
    if mode == "SSB":
        return "asr"
    if mode == "SSB_TRAFFIC":
        return "internal_ssb_occupancy"
    return "dsp"


def normalize_callsign(value):
    if not value:
        return None
    raw = str(value).strip().upper()
    # Preserve SSID (e.g. CT4TX-16) — strip only truly invalid chars
    cleaned = re.sub(r"[^A-Za-z0-9/\-]", "", raw)
    return cleaned or None


# ITU amateur radio callsign format:
# prefix (1-2 letters, or digit+letter) + digit(s) + suffix (1-4 letters)
# Optional portable indicator (/P, /M, /1, etc.)
# Valid: CT7BFV, K1DX, 9A1AA, VU2ABC, EA1XYZ/P
# Invalid: 121121, 5I5I, 999, ABCDEF
_VALID_CALLSIGN_RE = re.compile(
    r"^(?:"
    r"(?:[A-Z]{1,2}\d|[A-Z]\d[A-Z])\d{0,3}[A-Z]{1,4}"   # letter-start prefix
    r"|"
    r"\d[A-Z]{1,2}\d{1,3}[A-Z]{2,4}"                      # digit-start prefix (min 2 suffix)
    r")(?:/[A-Z0-9]{1,4})?$"
)


def is_valid_callsign(value):
    """Return True if *value* looks like a plausible amateur-radio callsign.
    Accepts optional SSID suffix (e.g. CT4TX-16)."""
    if not value:
        return False
    # Strip SSID before validation (e.g. CT4TX-16 → CT4TX)
    base = str(value).upper().split("-")[0]
    return bool(_VALID_CALLSIGN_RE.match(base))


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
    # Reject strings that don't look like a real amateur callsign
    if callsign and not is_valid_callsign(callsign):
        callsign = None
    if not callsign:
        # For CW, allow events without an identified callsign so that decoded
        # text and occupancy data are still recorded (callsign stored as "").
        if mode == "CW" and payload.get("msg"):
            callsign = ""
        elif mode == "CW_CANDIDATE" and payload.get("msg"):
            callsign = ""
        elif mode in ("SSB", "SSB_TRAFFIC") and (payload.get("msg") or payload.get("raw")):
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
    for _key in (
        "occupancy_rms",
        "occupancy_peak",
        "wpm",
        "crest_db",
        "ssb_state",
        "ssb_score",
        "ssb_parse_method",
    ):
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
        "crest_db": payload.get("crest_db"),
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
        "scan_id": payload.get("scan_id") or scan_state.get("scan_id"),
        "power_dbm": payload.get("power_dbm"),
        "rf_gated": payload.get("rf_gated"),
        "weather": payload.get("weather"),
        "symbol_table": payload.get("symbol_table"),
        "symbol_code": payload.get("symbol_code"),
    }
