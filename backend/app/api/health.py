# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Health and devices API endpoints

"""
Health and Devices API
======================
Basic system health and SDR device information endpoints.
"""

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import state
from app.dependencies.auth import verify_basic_auth
from app.version import APP_VERSION


router = APIRouter()


@router.get("/health")
def health(_: None = Depends(verify_basic_auth)) -> Dict:
    """
    Health check endpoint.
    
    Returns system status and detected device count.
    """
    sdr_devices = [
        d for d in state.controller.list_devices()
        if str(d.get("type", "")).lower() not in ("audio",)
    ]
    return {
        "status": "ok",
        "version": APP_VERSION,
        "devices": len(sdr_devices)
    }


@router.get("/devices")
def devices(
    _: None = Depends(verify_basic_auth),
    force: bool = Query(False, description="Bypass enumeration cache"),
) -> List[Dict]:
    """
    List available SDR devices.
    
    Returns list of detected devices with their capabilities.
    """
    return state.controller.list_devices(force=force)


@router.get("/bands")
def bands(_: None = Depends(verify_basic_auth)) -> List[Dict]:
    """
    Get all configured frequency bands.
    
    Returns list of band definitions from database.
    """
    return state.db.get_bands()


@router.post("/bands")
def save_band(payload: dict, _: None = Depends(verify_basic_auth)) -> Dict:
    """
    Save or update a frequency band configuration.
    
    Args:
        payload: Dict with 'band' key containing band configuration
        
    Returns:
        Status dict
        
    Raises:
        HTTPException: 400 if band range is invalid
    """
    band = payload.get("band", {})
    start_hz = int(band.get("start_hz", 0))
    end_hz = int(band.get("end_hz", 0))
    
    if start_hz <= 0 or end_hz <= 0 or start_hz >= end_hz:
        raise HTTPException(status_code=400, detail="Invalid band range")
    
    state.db.upsert_band(band)
    return {"status": "ok"}
