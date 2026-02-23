# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Settings API endpoints

"""
Settings API
============
Application settings management endpoints.
"""

from typing import Dict

from fastapi import APIRouter, Depends

from app.dependencies import state
from app.dependencies.auth import verify_basic_auth


router = APIRouter()


@router.get("")
def get_settings(_: None = Depends(verify_basic_auth)) -> Dict:
    """
    Get current application settings.
    
    Returns settings including modes, bands, favorites, station info, etc.
    
    Returns:
        Settings dict
    """
    settings = state.db.get_settings()
    modes = settings.get("modes") or {}
    settings["modes"] = {
        "ft8": bool(modes.get("ft8", state.default_modes["ft8"])),
        "aprs": bool(modes.get("aprs", state.default_modes["aprs"])),
        "cw": bool(modes.get("cw", state.default_modes["cw"])),
        "ssb": bool(modes.get("ssb", state.default_modes["ssb"])),
    }
    if "summary" not in settings:
        settings["summary"] = {"showBand": True, "showMode": True}
    return settings


@router.post("")
def save_settings(payload: dict, _: None = Depends(verify_basic_auth)) -> Dict:
    """
    Save application settings.
    
    Updates existing settings with provided values. Partial updates supported.
    
    Args:
        payload: Settings dict with keys:
            - band: Selected band
            - device_id: Selected device ID
            - auth_hint: Authentication hint
            - bands: Custom bands list
            - favorites: Favorite frequencies
            - modes: Mode enable/disable flags
            - summary: Summary display options
            - station: Station configuration
            - device_config: Device configuration
            - audio_config: Audio configuration
            
    Returns:
        Status dict
    """
    existing = state.db.get_settings()
    
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
            "ft8": bool(modes.get("ft8", state.default_modes["ft8"])),
            "aprs": bool(modes.get("aprs", state.default_modes["aprs"])),
            "cw": bool(modes.get("cw", state.default_modes["cw"])),
            "ssb": bool(modes.get("ssb", state.default_modes["ssb"])),
        }
    
    if payload.get("summary"):
        existing["summary"] = payload.get("summary")
    if "station" in payload:
        existing["station"] = payload.get("station") or {}
    if "device_config" in payload:
        existing["device_config"] = payload.get("device_config") or {}
    if "audio_config" in payload:
        existing["audio_config"] = payload.get("audio_config") or {}
    
    state.db.save_settings(existing)
    return {"status": "ok"}


@router.get("/defaults")
def get_settings_defaults(_: None = Depends(verify_basic_auth)) -> Dict:
    """
    Get default settings values.
    
    Returns the application's default settings without modifying current settings.
    
    Returns:
        Default settings dict
    """
    defaults = state.default_settings_payload()
    return defaults


@router.post("/reset-defaults")
def reset_settings_defaults(_: None = Depends(verify_basic_auth)) -> Dict:
    """
    Reset settings to default values.
    
    Clears all custom settings and restores application defaults.
    
    Returns:
        Status dict with default settings
    """
    defaults = state.default_settings_payload()
    state.db.save_settings(defaults)
    return {"status": "ok", "settings": defaults}
