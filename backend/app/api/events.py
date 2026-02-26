# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-23 21:30 UTC
# Events API endpoints

"""
Events API
==========
Event query, statistics, and propagation endpoints.
"""

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.dependencies import state
from app.dependencies.auth import verify_basic_auth, optional_verify_basic_auth
from app.dependencies.helpers import sanitize_events_for_api, build_propagation_summary


router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.get("/events")
@limiter.limit("30/minute")  # Rate limit: 30 requests per minute
def events(
    request: Request,
    limit: int = 1000,
    offset: int = 0,
    band: Optional[str] = None,
    mode: Optional[str] = None,
    callsign: Optional[str] = None,
    snr_min: Optional[float] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    format: Optional[str] = None,
    _: bool = Depends(optional_verify_basic_auth)
):
    """
    Query events with optional filters.
    
    Supports pagination, filtering by band/mode/callsign/time, and CSV export.
    
    Args:
        limit: Maximum number of events to return (default: 1000)
        offset: Offset for pagination (default: 0)
        band: Filter by band name
        mode: Filter by mode (FT8, APRS, etc.)
        callsign: Filter by callsign
        start: Start timestamp (ISO format)
        end: End timestamp (ISO format)
        format: Response format ('csv' or default JSON)
        
    Returns:
        List of events (JSON) or CSV text
    """
    data = state.db.get_events(
        limit=limit,
        offset=offset,
        band=band,
        mode=mode,
        callsign=callsign,
        snr_min=snr_min,
        start=start,
        end=end
    )
    data = sanitize_events_for_api(data)
    
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


@router.get("/events/export/csv")
@limiter.limit("10/minute")  # Rate limit: 10 requests per minute for exports
def export_events_csv(
    request: Request,
    limit: int = 1000,
    offset: int = 0,
    band: Optional[str] = None,
    mode: Optional[str] = None,
    callsign: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    _: bool = Depends(optional_verify_basic_auth)
):
    """
    Export events as CSV.
    
    Optimized CSV export endpoint with rate limiting.
    
    Args:
        limit: Maximum number of events to export (default: 1000, max: 10000)
        offset: Offset for pagination (default: 0)
        band: Filter by band name
        mode: Filter by mode (FT8, APRS, etc.)
        callsign: Filter by callsign
        start: Start timestamp (ISO format)
        end: End timestamp (ISO format)
        
    Returns:
        CSV text response with event data
    """
    if limit > 10000:
        limit = 10000
    
    data = state.db.get_events(
        limit=limit,
        offset=offset,
        band=band,
        mode=mode,
        callsign=callsign,
        start=start,
        end=end
    )
    data = sanitize_events_for_api(data)
    
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


@router.get("/events/export/json")
@limiter.limit("10/minute")  # Rate limit: 10 requests per minute for exports
def export_events_json(
    request: Request,
    limit: int = 1000,
    offset: int = 0,
    band: Optional[str] = None,
    mode: Optional[str] = None,
    callsign: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    _: bool = Depends(optional_verify_basic_auth)
) -> Dict:
    """
    Export events as JSON.
    
    Optimized JSON export endpoint with rate limiting.
    
    Args:
        limit: Maximum number of events to export (default: 1000, max: 10000)
        offset: Offset for pagination (default: 0)
        band: Filter by band name
        mode: Filter by mode (FT8, APRS, etc.)
        callsign: Filter by callsign
        start: Start timestamp (ISO format)
        end: End timestamp (ISO format)
        
    Returns:
        JSON dict with events array and metadata
    """
    if limit > 10000:
        limit = 10000
    
    data = state.db.get_events(
        limit=limit,
        offset=offset,
        band=band,
        mode=mode,
        callsign=callsign,
        start=start,
        end=end
    )
    data = sanitize_events_for_api(data)
    
    return {
        "status": "ok",
        "count": len(data),
        "limit": limit,
        "offset": offset,
        "events": data
    }


@router.post("/admin/events/purge-invalid")
def admin_purge_invalid_events(_: None = Depends(verify_basic_auth)) -> Dict:
    """
    Admin endpoint to purge invalid events from database.
    
    Returns:
        Status dict with purge results
    """
    result = state.db.purge_invalid_events()
    return {
        "status": "ok",
        "purge": result,
    }


@router.get("/events/count")
def events_count(
    band: Optional[str] = None,
    mode: Optional[str] = None,
    callsign: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    _: bool = Depends(optional_verify_basic_auth)
) -> Dict:
    """
    Get count of events matching filters (cached).
    
    Uses cache to avoid repeated expensive queries.
    Cache expires after 10 seconds.
    
    Args:
        band: Filter by band
        mode: Filter by mode
        callsign: Filter by callsign
        start: Start timestamp
        end: End timestamp
        
    Returns:
        Dict with count
    """
    import time
    
    cache_key = f"{band}|{mode}|{callsign}|{start}|{end}"
    now = time.time()
    
    # Check cache (10 second TTL)
    if (state.count_cache.get("key") == cache_key and
        now - state.count_cache.get("timestamp", 0) < 10):
        return {"count": state.count_cache["value"]}
    
    # Query database
    count = state.db.count_events(
        band=band,
        mode=mode,
        callsign=callsign,
        start=start,
        end=end
    )
    
    # Update cache
    state.count_cache["timestamp"] = now
    state.count_cache["value"] = count
    state.count_cache["key"] = cache_key
    
    return {"count": count}


@router.get("/events/stats")
def events_stats(_: bool = Depends(optional_verify_basic_auth)) -> Dict:
    """
    Get event statistics (counts by band, mode).
    
    Returns:
        Dict with stats grouped by band and mode
    """
    return state.db.get_event_stats()


@router.get("/propagation/summary")
@router.get("/events/propagation_summary")  # Alias for compatibility
def propagation_summary(
    window_minutes: int = 30,
    _: bool = Depends(optional_verify_basic_auth)
) -> Dict:
    """
    Get propagation conditions summary.
    
    Calculates propagation score per band based on recent events.
    Score considers SNR, confidence, recency, and event type.
    
    Args:
        window_minutes: Time window in minutes (default: 30)
        
    Returns:
        Dict with overall score and per-band metrics
    """
    return build_propagation_summary(window_minutes=window_minutes)
