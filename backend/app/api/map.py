# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

"""
Map API
=======
Provides geo-resolved contact data for the propagation world map.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict

from fastapi import APIRouter, Depends
from app.dependencies import state
from app.dependencies.auth import optional_verify_basic_auth
from app.dependencies.helpers import (
    callsign_to_dxcc,
    maidenhead_to_latlon,
    haversine_km,
)

router = APIRouter()


@router.get("/map/contacts")
def map_contacts(
    window_minutes: int = 60,
    limit: int = 2000,
    _: bool = Depends(optional_verify_basic_auth),
) -> Dict:
    """
    Return geo-resolved contacts for the propagation map.

    Resolves each decoded callsign to DXCC coordinates using longest-prefix-match
    against the cty.dat-derived index.  Station QTH is taken from saved settings
    (station.locator Maidenhead grid square).

    Args:
        window_minutes: Time window in minutes (default 60)
        limit: Maximum contacts to return (default 2000)

    Returns:
        Dict with station coords, contact list, and metadata
    """
    safe_window = max(1, min(int(window_minutes or 60), 10080))  # cap at 1 week
    safe_limit = max(10, min(int(limit or 2000), 2000))

    # ── Station QTH from saved settings ─────────────────────────────────────
    settings = state.db.get_settings()
    station = settings.get("station") or {}
    locator = str(station.get("locator") or "").strip().upper()
    station_callsign = str(station.get("callsign") or "").strip().upper()

    station_lat: float | None = None
    station_lon: float | None = None
    if locator:
        pos = maidenhead_to_latlon(locator)
        if pos:
            station_lat, station_lon = pos

    # Fallback: resolve own callsign through DXCC if no locator
    if station_lat is None and station_callsign:
        dxcc = callsign_to_dxcc(station_callsign)
        if dxcc:
            station_lat = dxcc.get("lat")
            station_lon = dxcc.get("lon")

    # Fallback: centre of Portugal (CT7BFV home)
    if station_lat is None or station_lon is None:
        station_lat = 39.5
        station_lon = -8.0

    # ── Fetch recent callsign events from DB ─────────────────────────────────
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=safe_window)

    rows = state.db.get_callsign_events(
        limit=safe_limit,
        start=start.isoformat(),
        end=now.isoformat(),
    )

    # ── Resolve each callsign → DXCC coords ─────────────────────────────────
    # Deduplicate by (callsign, band) so the same station shows an arc per band
    seen: Dict[str, dict] = {}

    for row in rows:
        cs = str(row.get("callsign") or "").strip().upper()
        if not cs:
            continue

        dxcc = callsign_to_dxcc(cs)
        if not dxcc:
            continue

        dest_lat = dxcc.get("lat")
        dest_lon = dxcc.get("lon")
        if dest_lat is None or dest_lon is None:
            continue

        snr = row.get("snr_db")
        band = str(row.get("band") or "")
        mode = str(row.get("mode") or "")
        ts = str(row.get("timestamp") or "")
        distance_km = haversine_km(station_lat, station_lon, dest_lat, dest_lon)

        key = f"{cs}|{band}"
        existing = seen.get(key)
        if existing is None or (snr is not None and (existing["snr_db"] is None or snr > existing["snr_db"])):
            seen[key] = {
                "callsign": cs,
                "lat": dest_lat,
                "lon": dest_lon,
                "country": dxcc.get("country", ""),
                "continent": dxcc.get("continent", ""),
                "cq_zone": dxcc.get("cq_zone"),
                "band": band,
                "mode": mode,
                "snr_db": snr,
                "distance_km": distance_km,
                "timestamp": ts,
            }

    contacts = sorted(seen.values(), key=lambda x: x.get("timestamp") or "", reverse=True)

    return {
        "status": "ok",
        "window_minutes": safe_window,
        "station": {
            "callsign": station_callsign,
            "locator": locator,
            "lat": station_lat,
            "lon": station_lon,
        },
        "contact_count": len(contacts),
        "contacts": contacts,
    }
