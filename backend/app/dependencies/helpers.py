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
    
    # Get bands from database
    bands = state.db.get_bands()
    for band in bands:
        start_hz = band.get("start_hz", 0)
        end_hz = band.get("end_hz", 0)
        if start_hz <= freq_hz <= end_hz:
            return band.get("name")
    
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


def build_propagation_summary(window_minutes: int = 30, limit: int = 3000) -> Dict:
    """
    Build propagation summary from recent events.
    
    Calculates propagation score per band based on recent events,
    considering SNR, confidence, and recency.
    
    Args:
        window_minutes: Time window in minutes
        limit: Maximum events to consider
        
    Returns:
        Dict with overall and per-band propagation metrics
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

    per_band = {}
    weighted_score_sum = 0.0
    weighted_sum = 0.0

    for event in events:
        band = str(event.get("band") or "Unknown")
        bucket = per_band.setdefault(
            band,
            {
                "band": band,
                "events": 0,
                "weighted_score_sum": 0.0,
                "weighted_sum": 0.0,
                "max_snr_db": None,
            }
        )

        event_type = str(event.get("type") or "")
        base_weight = 1.0 if event_type == "callsign" else 0.55

        parsed_ts = parse_event_timestamp(event.get("timestamp"))
        recency_weight = 0.6
        if parsed_ts is not None:
            age_minutes = max(0.0, (now - parsed_ts).total_seconds() / 60.0)
            recency_weight = clamp(1.0 - (age_minutes / safe_window_minutes), 0.2, 1.0)

        raw_snr = safe_float(event.get("snr_db"), default=None)
        snr_norm = 0.5
        if raw_snr is not None:
            snr_norm = clamp((raw_snr + 20.0) / 40.0, 0.0, 1.0)
            previous_max = bucket["max_snr_db"]
            bucket["max_snr_db"] = raw_snr if previous_max is None else max(previous_max, raw_snr)

        confidence_default = 0.6 if event_type == "callsign" else 0.5
        confidence = clamp(safe_float(event.get("confidence"), default=confidence_default), 0.0, 1.0)

        combined_weight = base_weight * recency_weight
        weighted_score = snr_norm * confidence * combined_weight

        bucket["events"] += 1
        bucket["weighted_score_sum"] += weighted_score
        bucket["weighted_sum"] += combined_weight

        weighted_score_sum += weighted_score
        weighted_sum += combined_weight

    # Calculate final scores
    def _score_to_state(score: float) -> str:
        if score >= 70:
            return "Excellent"
        if score >= 50:
            return "Good"
        if score >= 30:
            return "Fair"
        return "Poor"

    bands = []
    for bucket in per_band.values():
        denom = bucket["weighted_sum"]
        raw_score = (bucket["weighted_score_sum"] / denom * 100.0) if denom > 0 else 0.0
        score_rounded = round(raw_score, 1)
        max_snr = bucket["max_snr_db"]
        bands.append({
            "band": bucket["band"],
            "score": score_rounded,
            "state": _score_to_state(score_rounded),
            "events": int(bucket["events"]),
            "max_snr_db": round(max_snr, 1) if max_snr is not None else None,
        })

    overall_score = round(
        (weighted_score_sum / weighted_sum * 100.0) if weighted_sum > 0 else 0.0, 1
    )

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


def touch_decoder_source(source: str) -> None:
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
    if snr is None or snr < 0:
        return False
    
    # Band-specific bandwidth checks
    hf_bands = {"160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m"}
    
    if band in hf_bands:
        # HF: typical modes 150 Hz (CW) to 5 kHz (SSB)
        if bw < 150 or bw > 5000:
            return False
    else:
        # VHF/UHF: reject very wide signals (likely interference)
        if bw > 25000:
            return False
    
    # Must be within scan band
    if not frequency_within_scan_band(freq, bandwidth_hz=bw):
        return False
    
    return True
