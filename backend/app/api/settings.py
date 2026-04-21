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

import os
from pathlib import Path

from fastapi import APIRouter, Depends

from app.dependencies import state
from app.dependencies.auth import verify_basic_auth
from app.dependencies.utils import command_exists
from app.decoders.ssb_asr import is_ssb_asr_available, set_asr_enabled


router = APIRouter()

# ---------------------------------------------------------------------------
# APRS / Direwolf auto-configuration helpers
# ---------------------------------------------------------------------------

_DIREWOLF_CONF_TEMPLATE = """\
# Direwolf configuration for 4ham-spectrum-analysis (APRS)
# Auto-generated — edit as needed.

MYCALL N0CALL

ADEVICE default null

CHANNEL 0
MODEM 1200

KISSPORT 8001
AGWPORT 0
"""


def _project_root() -> Path:
    """Return the project root (parent of backend/)."""
    return Path(__file__).resolve().parent.parent.parent.parent


def _ensure_aprs_config():
    """Create direwolf.conf + set runtime env vars if not already configured.

    Called when the user enables APRS from Admin Config.  Ensures:
    1. ``config/direwolf.conf`` exists (created from template if missing).
    2. ``DIREWOLF_KISS_ENABLE``, ``DIREWOLF_AUTOSTART``, and
       ``DIREWOLF_CMD`` are set in ``os.environ`` so the current process
       can start Direwolf without a restart.
    3. The same values are persisted to the ``.env`` file so they survive
       a backend restart.
    4. ``state.decoder_status["direwolf_kiss"]`` flags are updated.
    """
    root = _project_root()
    conf_path = root / "config" / "direwolf.conf"

    # 1. Create config/direwolf.conf if it doesn't exist
    if not conf_path.exists():
        conf_path.parent.mkdir(parents=True, exist_ok=True)
        conf_path.write_text(_DIREWOLF_CONF_TEMPLATE)

    # 2. Set runtime env vars
    os.environ["DIREWOLF_KISS_ENABLE"] = "1"
    os.environ["DIREWOLF_AUTOSTART"] = "1"
    if not os.environ.get("DIREWOLF_CMD"):
        os.environ["DIREWOLF_CMD"] = f"direwolf -t 0 -p -c {conf_path}"

    # 3. Persist to .env file
    _persist_env_vars(root / ".env", {
        "DIREWOLF_KISS_ENABLE": "1",
        "DIREWOLF_AUTOSTART": "1",
        "DIREWOLF_CMD": os.environ["DIREWOLF_CMD"],
    })

    # 4. Update runtime state
    kiss_st = state.decoder_status["direwolf_kiss"]
    kiss_st["enabled"] = True
    kiss_st["autostart"] = True


def _persist_env_vars(env_path: Path, env_vars: dict):
    """Add or update key=value pairs in a .env file."""
    lines = []
    if env_path.exists():
        lines = env_path.read_text().splitlines()

    for key, value in env_vars.items():
        found = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{key}=") or stripped.startswith(f"export {key}="):
                lines[i] = f"{key}={value}"
                found = True
                break
        if not found:
            lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines) + "\n")


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
        "ft4": bool(modes.get("ft4", state.default_modes["ft4"])),
        "wspr": bool(modes.get("wspr", state.default_modes["wspr"])),
        "aprs": bool(modes.get("aprs", state.default_modes["aprs"])),
        "cw": bool(modes.get("cw", state.default_modes["cw"])),
        "ssb": bool(modes.get("ssb", state.default_modes["ssb"])),
    }
    if "summary" not in settings:
        settings["summary"] = {"showBand": True, "showMode": True}
    asr_cfg = settings.get("asr") or {}
    settings["asr"] = {
        "enabled": bool(asr_cfg.get("enabled", True)),
        "available": is_ssb_asr_available(),
    }
    aprs_cfg = settings.get("aprs") or {}
    kiss_st = state.decoder_status.get("direwolf_kiss") or {}
    settings["aprs"] = {
        "enabled": bool(kiss_st.get("enabled", False)),
        "available": command_exists("direwolf"),
        "connected": bool(kiss_st.get("connected", False)),
        "autostart": bool(kiss_st.get("autostart", False)),
        "address": kiss_st.get("address"),
    }
    settings["auth"] = {
        "enabled": bool(state.auth_required),
        "user": state.auth_user if state.auth_required else "",
        "password_configured": bool(state.auth_pass),
    }
    return settings


@router.post("")
async def save_settings(payload: dict, _: None = Depends(verify_basic_auth)) -> Dict:
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
            "ft4": bool(modes.get("ft4", state.default_modes["ft4"])),
            "wspr": bool(modes.get("wspr", state.default_modes["wspr"])),
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
    if "asr" in payload:
        asr = payload.get("asr") or {}
        enabled = bool(asr.get("enabled", True))
        existing["asr"] = {"enabled": enabled}
        set_asr_enabled(enabled)

    if "aprs" in payload:
        from app.api.decoders import _start_kiss_loop, _stop_kiss_loop
        import asyncio
        aprs = payload.get("aprs") or {}
        aprs_enabled = bool(aprs.get("enabled", False))
        kiss_st = state.decoder_status.get("direwolf_kiss") or {}
        currently_enabled = bool(kiss_st.get("enabled", False))
        if aprs_enabled and not currently_enabled:
            _ensure_aprs_config()
            asyncio.create_task(_start_kiss_loop(force=True))
        elif not aprs_enabled and currently_enabled:
            asyncio.create_task(_stop_kiss_loop())
            state.decoder_status["direwolf_kiss"]["enabled"] = False
        existing["aprs"] = {"enabled": aprs_enabled}

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
