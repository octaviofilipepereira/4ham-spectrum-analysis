# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Helper functions

"""
Helper Functions
================
Shared helper functions for API endpoints.
"""

import json
import math
import re
from datetime import datetime, timezone, timedelta
from functools import lru_cache
from pathlib import Path
from statistics import median
from typing import Optional, List, Dict, Any, Tuple

from app.dependencies import state

# ─── DXCC coords index (lazy-loaded once) ───────────────────────────────────

_DXCC_PATH = Path(__file__).resolve().parents[3] / "prefixes" / "dxcc_coords.json"
_dxcc_index: Optional[Dict[str, Dict]] = None


def _load_dxcc_index() -> Dict[str, Dict]:
    """Load and cache the DXCC prefix→coords index from dxcc_coords.json."""
    global _dxcc_index
    if _dxcc_index is None:
        try:
            with open(_DXCC_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            _dxcc_index = data.get("index", {})
        except Exception:
            _dxcc_index = {}
    return _dxcc_index


def callsign_to_dxcc(callsign: str) -> Optional[Dict]:
    """
    Resolve a callsign to its DXCC entity using longest-prefix-match.

    Args:
        callsign: Amateur radio callsign (e.g. 'DL1ABC', 'CT7BFV')

    Returns:
        Dict with country, lat, lon, continent, cq_zone or None if not found
    """
    if not callsign:
        return None
    cs = callsign.upper().strip()
    # Strip portable suffixes (/P /M /QRP etc.)
    cs = re.sub(r"/(P|M|MM|QRP|QRPP|A|B)$", "", cs)
    index = _load_dxcc_index()
    # Try longest prefix first (up to 5 chars)
    for length in range(min(len(cs), 5), 0, -1):
        candidate = cs[:length]
        if candidate in index:
            return dict(index[candidate])
    return None


def maidenhead_to_latlon(grid: str) -> Optional[Tuple[float, float]]:
    """
    Convert a Maidenhead grid square locator to (lat, lon) centre coordinates.

    Supports 4-character (e.g. IN60) and 6-character (e.g. IN60aa) locators.

    Args:
        grid: Maidenhead locator string

    Returns:
        (lat, lon) tuple in decimal degrees, or None if invalid
    """
    if not grid or len(grid) < 4:
        return None
    g = grid.strip().upper()
    if not re.match(r"^[A-R]{2}[0-9]{2}([A-X]{2})?$", g):
        return None
    lon = (ord(g[0]) - ord("A")) * 20.0 - 180.0
    lat = (ord(g[1]) - ord("A")) * 10.0 - 90.0
    lon += int(g[2]) * 2.0
    lat += int(g[3]) * 1.0
    if len(g) >= 6:
        lon += (ord(g[4]) - ord("A")) * (2.0 / 24.0)
        lat += (ord(g[5]) - ord("A")) * (1.0 / 24.0)
        lon += 1.0 / 24.0   # centre of subsquare
        lat += 0.5 / 24.0
    else:
        lon += 1.0          # centre of square
        lat += 0.5
    return (round(lat, 5), round(lon, 5))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    r = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(d_lon / 2) ** 2)
    return round(r * 2 * math.asin(math.sqrt(a)), 1)


def log(message: str) -> None:
    """
    Log a message to the application logs.
    
    Args:
        message: Message to log
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    state.logs.append(f"{timestamp} {message}")
    # No manual trim needed: state.logs is a deque(maxlen=500)


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    """
    Safely convert value to float.
    
    Args:
        value: Value to convert
        default: Default value if conversion fails
        
    Returns:
        Float value or default
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value: float, minimum: float, maximum: float) -> float:
    """
    Clamp value between minimum and maximum.
    
    Args:
        value: Value to clamp
        minimum: Minimum allowed value
        maximum: Maximum allowed value
        
    Returns:
        Clamped value
    """
    return max(minimum, min(maximum, value))


def parse_event_timestamp(timestamp_str: str) -> Optional[datetime]:
    """
    Parse event timestamp string to datetime.
    
    Args:
        timestamp_str: ISO format timestamp string
        
    Returns:
        Datetime object or None if parsing fails
    """
    if not timestamp_str:
        return None
    try:
        return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except Exception:
        return None


_FALLBACK_BANDS = [
    ("160m", 1_810_000, 2_000_000),
    ("80m",  3_500_000, 3_800_000),
    ("60m",  5_250_000, 5_450_000),
    ("40m",  7_000_000, 7_200_000),
    ("30m",  10_100_000, 10_150_000),
    ("20m",  14_000_000, 14_350_000),
    ("17m",  18_068_000, 18_168_000),
    ("15m",  21_000_000, 21_450_000),
    ("12m",  24_890_000, 24_990_000),
    ("10m",  28_000_000, 29_700_000),
    ("6m",   50_000_000, 54_000_000),
    ("2m",   144_000_000, 146_000_000),
]


def infer_band_from_frequency(frequency_hz: float) -> Optional[str]:
    """
    Infer frequency band name from frequency in Hz.
    
    Args:
        frequency_hz: Frequency in Hz
        
    Returns:
        Band name or None
    """
    freq_hz = safe_float(frequency_hz)
    if freq_hz is None or freq_hz <= 0:
        return None
    
    # Get bands from database; fall back to hardcoded IARU Region 1 table
    bands = state.db.get_bands()
    if bands:
        for band in bands:
            start_hz = band.get("start_hz", 0)
            end_hz = band.get("end_hz", 0)
            if start_hz <= freq_hz <= end_hz:
                return band.get("name")
    else:
        for name, start_hz, end_hz in _FALLBACK_BANDS:
            if start_hz <= freq_hz <= end_hz:
                return name
    
    return None


def sanitize_events_for_api(items: List[Dict]) -> List[Dict]:
    """
    Sanitize events list for API response.
    
    Filters out invalid occupancy events and infers missing bands.
    
    Args:
        items: List of event dicts
        
    Returns:
        Sanitized list of events
    """
    sanitized = []
    for item in items or []:
        row = dict(item)

        # Backward compatibility: older callsign rows may carry CW metrics
        # only inside payload JSON; expose crest_db at top-level for the UI.
        if row.get("crest_db") is None and str(row.get("type") or "") == "callsign":
            payload = row.get("payload")
            payload_obj = None
            if isinstance(payload, dict):
                payload_obj = payload
            elif isinstance(payload, str) and payload.strip():
                try:
                    payload_obj = json.loads(payload)
                except Exception:
                    payload_obj = None
            if isinstance(payload_obj, dict) and payload_obj.get("crest_db") is not None:
                row["crest_db"] = payload_obj.get("crest_db")
        
        # Filter invalid occupancy events
        if str(row.get("type") or "") == "occupancy":
            freq = safe_float(row.get("frequency_hz"), default=0.0) or 0.0
            band = str(row.get("band") or "").strip()
            scan_id = row.get("scan_id")
            mode = str(row.get("mode") or "").strip().lower()
            occupied = bool(row.get("occupied"))
            
            # Invalid noise: unoccupied, no freq, no band, unknown mode
            invalid_noise = (not occupied) and freq <= 0 and (not band or band.lower() == "null") and mode == "unknown"
            # Invalid unbound: no scan, no freq, no band
            invalid_unbound = (scan_id is None) and freq <= 0 and (not band or band.lower() == "null")
            
            if invalid_noise or invalid_unbound:
                continue
        
        # Infer band if missing
        if not row.get("band"):
            inferred_band = infer_band_from_frequency(row.get("frequency_hz"))
            if inferred_band:
                row["band"] = inferred_band
        
        sanitized.append(row)
    
    return sanitized


# ─── Mode categories for propagation scoring ────────────────────────────────
# See docs/propagation_scoring_reference.md for full rationale.

_DIGITAL_WIDEBAND_MODES = frozenset({"FT8", "FT4", "WSPR", "JT65", "JT9", "FST4", "FST4W", "Q65"})
_CW_MODES = frozenset({"CW", "CW_CANDIDATE", "CW_TRAFFIC"})
_SSB_MODES = frozenset({"SSB", "SSB_TRAFFIC", "AM", "VOICE_DETECTION"})

# SNR normalisation parameters per mode (floor, ceiling)
_SNR_PARAMS: Dict[str, Tuple[float, float]] = {
    "FT8":  (-20.0, 10.0),
    "FT4":  (-17.5, 10.0),
    "WSPR": (-31.0,  0.0),
    "JT65": (-25.0,  5.0),
    "JT9":  (-26.0,  5.0),
    "FST4": (-28.0,  2.0),
    "FST4W":(-33.0,  0.0),
    "Q65":  (-22.0,  8.0),
    "CW":   (-15.0, 20.0),
    "CW_CANDIDATE": (-15.0, 20.0),
    "SSB":  (  3.0, 30.0),
    "SSB_TRAFFIC": (3.0, 30.0),
    "AM":   (  3.0, 30.0),
    "VOICE_DETECTION": (3.0, 30.0),
}
_DEFAULT_SNR_PARAMS = (-20.0, 10.0)


def _mode_category(mode: str) -> str:
    """Return 'digital', 'cw', or 'ssb' for a given mode name."""
    m = mode.upper()
    if m in _DIGITAL_WIDEBAND_MODES:
        return "digital"
    if m in _CW_MODES:
        return "cw"
    if m in _SSB_MODES:
        return "ssb"
    return "digital"  # default fallback


def _normalise_snr(snr_db: float, mode: str) -> float:
    """Normalise SNR to 0-1 using mode-specific floor/ceiling."""
    floor, ceiling = _SNR_PARAMS.get(mode.upper(), _DEFAULT_SNR_PARAMS)
    rng = ceiling - floor
    if rng <= 0:
        return 0.5
    return clamp((snr_db - floor) / rng, 0.0, 1.0)


def _score_to_state(score: float) -> str:
    if score >= 70:
        return "Excellent"
    if score >= 50:
        return "Good"
    if score >= 30:
        return "Fair"
    return "Poor"


def _compute_band_propagation(band_data: Dict) -> Dict:
    """
    Compute propagation score for a single band — confirmed decodes only.

    Only events with a verified callsign contribute to propagation scoring.
    Events without a callsign reflect band occupancy but do not affect the score.
    This applies universally across all mode categories.
    """
    cat_scores = []
    cat_weights = []

    # ── Digital wideband (FT8/FT4/WSPR) ──────────────────────────────
    d = band_data.get("digital")
    if d and d["total_events"] > 0:
        decode_rate = d["callsign_events"] / d["total_events"] if d["total_events"] > 0 else 0.0
        snr_list = d["snr_values"]
        snr_component = _normalise_snr(median(snr_list), d["dominant_mode"]) if snr_list else 0.0
        callsign_norm = clamp(math.log1p(d["unique_callsigns"]) / math.log1p(20), 0.0, 1.0)
        recency_component = d["avg_recency"]

        score = 100.0 * (
            0.40 * decode_rate +
            0.35 * snr_component +
            0.15 * callsign_norm +
            0.10 * recency_component
        )
        cat_scores.append(clamp(score, 0.0, 100.0))
        cat_weights.append(d["total_events"])

    # ── CW — confirmed decodes only ──────────────────────────────────
    c = band_data.get("cw")
    if c and c["callsign_events"] > 0:
        cs_n = c["callsign_events"]
        snr_list = c["cs_snr_values"]
        snr_component = _normalise_snr(median(snr_list), "CW") if snr_list else 0.0
        pwr_list = c["cs_power_values"]
        signal_component = clamp((median(pwr_list) + 120.0) / 70.0, 0.0, 1.0) if pwr_list else 0.3
        callsign_norm = clamp(math.log1p(c["unique_callsigns"]) / math.log1p(20), 0.0, 1.0)
        recency_component = c["cs_avg_recency"]

        score = 100.0 * (
            0.35 * snr_component +
            0.25 * callsign_norm +
            0.20 * signal_component +
            0.20 * recency_component
        )
        cat_scores.append(clamp(score, 0.0, 100.0))
        cat_weights.append(cs_n)

    # ── SSB — confirmed decodes only ─────────────────────────────────
    sb = band_data.get("ssb")
    if sb and sb["callsign_events"] > 0:
        cs_n = sb["callsign_events"]
        snr_list = sb["cs_snr_values"]
        snr_component = _normalise_snr(median(snr_list), "SSB") if snr_list else 0.0
        pwr_list = sb["cs_power_values"]
        signal_component = clamp((median(pwr_list) + 120.0) / 70.0, 0.0, 1.0) if pwr_list else 0.3
        callsign_norm = clamp(math.log1p(sb["unique_callsigns"]) / math.log1p(20), 0.0, 1.0)
        recency_component = sb["cs_avg_recency"]

        score = 100.0 * (
            0.35 * snr_component +
            0.25 * callsign_norm +
            0.20 * signal_component +
            0.20 * recency_component
        )
        cat_scores.append(clamp(score, 0.0, 100.0))
        cat_weights.append(cs_n)

    if not cat_scores:
        return {"score": 0.0, "state": "Poor"}

    # Weighted average across categories present in this band
    total_w = sum(cat_weights)
    band_score = sum(sc * w for sc, w in zip(cat_scores, cat_weights)) / total_w if total_w > 0 else 0.0
    return {"score": round(band_score, 1), "state": _score_to_state(band_score)}


def build_propagation_summary(window_minutes: int = 30, limit: int = 3000) -> Dict:
    """
    Build propagation summary — confirmed decodes only.

    Only events with a verified callsign contribute to propagation scoring.
    Events without a callsign reflect band occupancy but do not affect the score.
    This applies universally across all mode categories (Digital, CW, SSB).

    See docs/propagation_scoring_reference.md for full design rationale.
    """
    safe_window_minutes = max(1, int(window_minutes or 30))
    safe_limit = max(100, min(int(limit or 3000), 10000))
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=safe_window_minutes)

    events = state.db.get_events(
        limit=safe_limit,
        start=start.isoformat(),
        end=now.isoformat()
    )

    # ── Aggregate per band × category ─────────────────────────────────
    per_band: Dict[str, Dict[str, Dict]] = {}

    def _empty_cat() -> Dict:
        return {
            "total_events": 0,
            "callsign_events": 0,
            "unique_callsigns": 0,
            "snr_values": [],
            "power_values": [],
            "recency_sum": 0.0,
            "avg_recency": 0.0,
            "avg_confidence": 0.0,
            "confidence_sum": 0.0,
            "has_transcript": False,
            "max_snr_db": None,
            "dominant_mode": "",
            "_callsign_set": set(),
            "_mode_counts": {},
            # Callsign-only metrics (used for CW/SSB confirmed-decode scoring)
            "cs_snr_values": [],
            "cs_power_values": [],
            "cs_recency_sum": 0.0,
            "cs_avg_recency": 0.0,
            "cs_confidence_sum": 0.0,
            "cs_avg_confidence": 0.0,
        }

    for event in events:
        band = str(event.get("band") or "").strip()
        if not band:
            continue

        mode_raw = str(event.get("mode") or "").strip().upper()
        if not mode_raw:
            continue

        cat = _mode_category(mode_raw)
        band_cats = per_band.setdefault(band, {})
        bucket = band_cats.get(cat)
        if bucket is None:
            bucket = _empty_cat()
            band_cats[cat] = bucket

        event_type = str(event.get("type") or "").strip().lower()
        bucket["total_events"] += 1

        # Mode frequency tracking for dominant_mode
        bucket["_mode_counts"][mode_raw] = bucket["_mode_counts"].get(mode_raw, 0) + 1

        # Callsign tracking
        is_callsign_event = event_type == "callsign"
        if is_callsign_event:
            bucket["callsign_events"] += 1
            callsign = str(event.get("callsign") or "").strip().upper()
            if callsign:
                bucket["_callsign_set"].add(callsign)

        # SNR
        raw_snr = safe_float(event.get("snr_db"), default=None)
        if raw_snr is not None:
            bucket["snr_values"].append(raw_snr)
            if is_callsign_event:
                bucket["cs_snr_values"].append(raw_snr)
            prev_max = bucket["max_snr_db"]
            bucket["max_snr_db"] = raw_snr if prev_max is None else max(prev_max, raw_snr)

        # Power (signal strength)
        raw_power = safe_float(event.get("power_dbm"), default=None)
        if raw_power is not None:
            bucket["power_values"].append(raw_power)
            if is_callsign_event:
                bucket["cs_power_values"].append(raw_power)

        # Recency
        parsed_ts = parse_event_timestamp(event.get("timestamp"))
        if parsed_ts is not None:
            age_minutes = max(0.0, (now - parsed_ts).total_seconds() / 60.0)
            recency = clamp(1.0 - (age_minutes / safe_window_minutes), 0.2, 1.0)
        else:
            recency = 0.5
        bucket["recency_sum"] += recency
        if is_callsign_event:
            bucket["cs_recency_sum"] += recency

        # Confidence
        conf = safe_float(event.get("confidence"), default=None)
        if conf is not None:
            bucket["confidence_sum"] += clamp(conf, 0.0, 1.0)
            if is_callsign_event:
                bucket["cs_confidence_sum"] += clamp(conf, 0.0, 1.0)

        # Transcript / raw text (SSB)
        if not bucket["has_transcript"]:
            raw_text = event.get("raw") or event.get("msg") or ""
            if isinstance(raw_text, str) and len(raw_text.strip()) > 2:
                bucket["has_transcript"] = True

    # ── Finalise per-category aggregates ──────────────────────────────
    for band_cats in per_band.values():
        for bucket in band_cats.values():
            n = bucket["total_events"]
            if n > 0:
                bucket["avg_recency"] = bucket["recency_sum"] / n
                bucket["avg_confidence"] = bucket["confidence_sum"] / n
                bucket["unique_callsigns"] = len(bucket["_callsign_set"])
                # Determine dominant mode
                if bucket["_mode_counts"]:
                    bucket["dominant_mode"] = max(bucket["_mode_counts"], key=bucket["_mode_counts"].get)
            # Callsign-only averages
            cs_n = bucket["callsign_events"]
            if cs_n > 0:
                bucket["cs_avg_recency"] = bucket["cs_recency_sum"] / cs_n
                bucket["cs_avg_confidence"] = bucket["cs_confidence_sum"] / cs_n
            # Clean up internal fields
            del bucket["_callsign_set"]
            del bucket["_mode_counts"]

    # ── Compute per-band scores ───────────────────────────────────────
    bands = []
    for band, band_cats in per_band.items():
        result = _compute_band_propagation(band_cats)
        total_events = sum(c["total_events"] for c in band_cats.values())
        total_callsigns = sum(c["unique_callsigns"] for c in band_cats.values())
        total_callsign_events = sum(c["callsign_events"] for c in band_cats.values())

        # Collect max SNR across all categories
        max_snr = None
        for c in band_cats.values():
            if c["max_snr_db"] is not None:
                max_snr = c["max_snr_db"] if max_snr is None else max(max_snr, c["max_snr_db"])

        # Determine dominant category label
        cat_events = {cat: c["total_events"] for cat, c in band_cats.items() if c["total_events"] > 0}
        dominant_category = max(cat_events, key=cat_events.get) if cat_events else "digital"

        decode_rate = (total_callsign_events / total_events) if total_events > 0 else None

        entry = {
            "band": band,
            "score": result["score"],
            "state": result["state"],
            "events": total_events,
            "max_snr_db": round(max_snr, 1) if max_snr is not None else None,
            "unique_callsigns": total_callsigns,
            "mode_category": dominant_category,
        }
        if decode_rate is not None:
            entry["decode_rate"] = round(decode_rate, 3)

        bands.append(entry)

    # ── Overall score (weighted by events) ────────────────────────────
    total_events_all = sum(b["events"] for b in bands)
    if total_events_all > 0:
        overall_score = sum(b["score"] * b["events"] for b in bands) / total_events_all
    else:
        overall_score = 0.0
    overall_score = round(overall_score, 1)

    bands.sort(key=lambda x: (x["score"], x["events"]), reverse=True)

    return {
        "status": "ok",
        "window_minutes": safe_window_minutes,
        "event_count": len(events),
        "overall": {
            "score": overall_score,
            "state": _score_to_state(overall_score),
        },
        "bands": bands,
    }


def touch_decoder_source(source: Optional[str]) -> None:
    """
    Update last seen timestamp for decoder source.
    
    Args:
        source: Decoder source name
    """
    if not source:
        return
    state.decoder_status["sources"][source] = datetime.now(timezone.utc).isoformat()


def record_decoder_event_saved(event: Dict) -> None:
    """
    Record metrics for saved decoder event.
    
    Args:
        event: Event dict
    """
    if not isinstance(event, dict):
        return
    
    state.decoder_runtime_metrics["callsign_saved"] = int(
        state.decoder_runtime_metrics.get("callsign_saved", 0)
    ) + 1
    
    # Track by source
    source = event.get("source")
    if source:
        state.decoder_runtime_metrics["by_source"].setdefault(source, 0)
        state.decoder_runtime_metrics["by_source"][source] += 1
    
    # Track by mode
    mode = event.get("mode")
    if mode:
        state.decoder_runtime_metrics["by_mode"].setdefault(mode, 0)
        state.decoder_runtime_metrics["by_mode"][mode] += 1


def record_decoder_event_invalid() -> None:
    """Record metrics for invalid decoder event."""
    state.decoder_runtime_metrics["invalid_events"] = int(
        state.decoder_runtime_metrics.get("invalid_events", 0)
    ) + 1


def fallback_sample_rate_for_device(device_id: str, current_sample_rate: int) -> Optional[int]:
    """
    Get fallback sample rate for device if current rate fails.
    
    Args:
        device_id: Device identifier
        current_sample_rate: Current sample rate that failed
        
    Returns:
        Fallback sample rate or None if same as current
    """
    from app.dependencies.utils import normalize_device_choice, device_profile
    
    choice = normalize_device_choice(device_id)
    fallback_rate = int(device_profile(choice).get("sample_rate", 48000) or 48000)
    current_rate = int(current_sample_rate or 0)
    
    if current_rate > 0 and current_rate == fallback_rate:
        return None
    
    return fallback_rate


def cpu_percent() -> Optional[float]:
    """
    Get current CPU utilization percentage.
    
    Returns:
        CPU percentage (0-100) or None if psutil unavailable
    """
    try:
        import psutil
        return psutil.cpu_percent(interval=None)
    except Exception:
        return None


def scan_band_bounds() -> tuple[Optional[int], Optional[int]]:
    """
    Get current scan band boundaries from scan engine.
    
    Returns:
        Tuple of (start_hz, end_hz) or (None, None) if not configured
    """
    if not state.scan_engine or not state.scan_engine.config:
        return None, None
    
    start_hz = int(safe_float(state.scan_engine.config.get("start_hz"), default=0) or 0)
    end_hz = int(safe_float(state.scan_engine.config.get("end_hz"), default=0) or 0)
    
    if start_hz <= 0 or end_hz <= 0 or end_hz <= start_hz:
        return None, None
    
    return int(start_hz), int(end_hz)


def frequency_within_scan_band(frequency_hz: Optional[float], bandwidth_hz: Optional[float] = None) -> bool:
    """
    Check if frequency (with optional bandwidth) falls within current scan band.
    
    Args:
        frequency_hz: Center frequency in Hz
        bandwidth_hz: Signal bandwidth in Hz (optional)
        
    Returns:
        True if frequency is within scan band, False otherwise
    """
    start_hz, end_hz = scan_band_bounds()
    
    if start_hz is None or end_hz is None:
        return True  # No bounds configured, allow all
    
    freq = safe_float(frequency_hz, default=None)
    if freq is None:
        return False
    
    # Account for bandwidth by checking edges
    half_bw = max(0.0, safe_float(bandwidth_hz, default=0.0) / 2.0)
    
    return (freq + half_bw) >= start_hz and (freq - half_bw) <= end_hz


def hint_mode_by_frequency(
    frequency_hz: Optional[float],
    band_name: Optional[str] = None,
    bandwidth_hz: Optional[float] = None
) -> Optional[str]:
    """
    Return specific digital mode name (FT8/FT4/WSPR) if frequency
    falls within a known digital-mode window.
    
    This refines DSP-based mode classification by checking against
    known frequency allocations for digital modes.
    
    Args:
        frequency_hz: Frequency in Hz
        band_name: Band name (e.g., "20m"), auto-inferred if None
        bandwidth_hz: Signal bandwidth in Hz (unused, for future)
        
    Returns:
        Mode name ("FT8", "FT4", "WSPR") or None if not in known window
    """
    freq = safe_float(frequency_hz, default=None)
    if freq is None or freq <= 0:
        return None
    
    # Infer band if not provided
    if not band_name:
        band_name = infer_band_from_frequency(freq)
    
    band = str(band_name or "").strip().lower()
    
    # Known digital mode frequency windows: (center_hz, tolerance_hz, mode_name)
    known_windows = {
        "20m": [(14_074_000, 2500, "FT8"), (14_080_000, 2000, "FT4"), (14_095_600, 2000, "WSPR")],
        "40m": [(7_074_000, 2500, "FT8"), (7_047_500, 2000, "FT4"), (7_038_600, 2000, "WSPR")],
        "80m": [(3_573_000, 2500, "FT8"), (3_575_500, 2000, "FT4"), (3_568_600, 2000, "WSPR")],
        "30m": [(10_136_000, 2000, "FT8"), (10_140_000, 2000, "FT4"), (10_138_700, 2000, "WSPR")],
        "17m": [(18_100_000, 2500, "FT8"), (18_104_000, 2000, "FT4")],
        "15m": [(21_074_000, 2500, "FT8"), (21_080_000, 2000, "FT4"), (21_094_600, 2000, "WSPR")],
        "12m": [(24_915_000, 2500, "FT8"), (24_919_000, 2000, "FT4")],
        "10m": [(28_074_000, 2500, "FT8"), (28_180_000, 3000, "FT4")],
        "6m": [(50_313_000, 2500, "FT8"), (50_318_000, 2000, "FT4")],
        "2m": [(144_174_000, 2500, "FT8")],
        "160m": [(1_840_000, 2500, "FT8"), (1_836_600, 2000, "WSPR")],
        "60m": [(5_357_000, 2500, "FT8")],
    }
    
    for center_hz, tolerance_hz, mode in known_windows.get(band, []):
        if abs(freq - center_hz) <= tolerance_hz:
            return mode
    
    return None


def is_plausible_occupancy_event(event: Dict[str, Any]) -> bool:
    """
    Validate if occupancy event is plausible based on frequency,
    bandwidth, SNR, and band characteristics.
    
    Filters out implausible detections to reduce false positives.
    
    Args:
        event: Event dictionary with frequency_hz, bandwidth_hz, snr_db, etc.
        
    Returns:
        True if event passes plausibility checks, False otherwise
    """
    if not isinstance(event, dict):
        return False
    
    if not bool(event.get("occupied")):
        return False
    
    freq = safe_float(event.get("frequency_hz"), default=None)
    bw = safe_float(event.get("bandwidth_hz"), default=None)
    snr = safe_float(event.get("snr_db"), default=None)
    band = str(event.get("band") or "").strip().lower()
    
    # Basic validation
    if freq is None or freq <= 0:
        return False
    if bw is None or bw <= 0:
        return False
    if snr is None:
        return False
    
    # Band-specific bandwidth checks
    hf_bands = {"160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m"}
    
    if band in hf_bands:
        # HF: typical modes 150 Hz (CW) to 2.8 kHz (SSB voice ceiling)
        if bw < 150 or bw > 2800:
            return False
    else:
        # VHF/UHF: reject very wide signals (likely interference)
        if bw > 25000:
            return False
    
    # Must be within scan band
    if not frequency_within_scan_band(freq, bandwidth_hz=bw):
        return False
    
    return True
