# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Helper functions

"""
Helper Functions
================
Shared helper functions for API endpoints.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from app.dependencies import state


def log(message: str) -> None:
    """
    Log a message to the application logs.
    
    Args:
        message: Message to log
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    state.logs.append(f"{timestamp} {message}")
    if len(state.logs) > 500:
        state.logs.pop(0)


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
    bands = []
    for bucket in per_band.values():
        denom = bucket["weighted_sum"]
        bucket["score"] = (bucket["weighted_score_sum"] / denom * 100.0) if denom > 0 else 0.0
        del bucket["weighted_score_sum"]
        del bucket["weighted_sum"]
        bands.append(bucket)

    overall_score = (weighted_score_sum / weighted_sum * 100.0) if weighted_sum > 0 else 0.0

    bands.sort(key=lambda x: x["score"], reverse=True)

    return {
        "overall_score": round(overall_score, 1),
        "window_minutes": safe_window_minutes,
        "total_events": len(events),
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
