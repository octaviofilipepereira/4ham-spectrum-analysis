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
import subprocess
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


# ---------------------------------------------------------------------------
# LoRa APRS auto-configuration helpers
# ---------------------------------------------------------------------------

def _gr_lora_sdr_available() -> bool:
    """Probe whether the gr-lora_sdr host install is available.

    The backend runs inside ``.venv``, while GNU Radio OOT modules are
    commonly installed into the system Python used by
    ``gnuradio-companion`` / external flowgraphs.  Check both
    interpreters so the Admin badge reflects the real host capability,
    not only the backend virtualenv.
    """
    try:
        import importlib.util
        if importlib.util.find_spec("gnuradio.lora_sdr") is not None:
            return True
    except Exception:
        pass

    try:
        probe = subprocess.run(
            [
                "python3",
                "-c",
                "import importlib.util, sys; "
                "sys.exit(0 if importlib.util.find_spec('gnuradio.lora_sdr') else 1)",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return probe.returncode == 0
    except Exception:
        return False


def _ensure_lora_aprs_config():
    """Set runtime + persisted env vars so the LoRa-APRS UDP listener can start.

    Called when the user enables LoRa APRS from Admin Config.  Ensures:
    1. ``LORA_APRS_ENABLE``, ``LORA_APRS_HOST`` and ``LORA_APRS_PORT`` are
       set in ``os.environ`` so the current process can start the loop
       without a restart.
    2. The same values are persisted to the ``.env`` file so they survive
       a backend restart.
    3. ``state.decoder_status["lora_aprs"]`` flags are updated.

    No external config file is needed: gr-lora_sdr ships its own
    flowgraphs and the backend just listens on a UDP socket.
    """
    root = _project_root()

    # 1. Set runtime env vars
    os.environ["LORA_APRS_ENABLE"] = "1"
    if not os.environ.get("LORA_APRS_HOST"):
        os.environ["LORA_APRS_HOST"] = "127.0.0.1"
    if not os.environ.get("LORA_APRS_PORT"):
        os.environ["LORA_APRS_PORT"] = "5687"

    # 2. Persist to .env file
    _persist_env_vars(root / ".env", {
        "LORA_APRS_ENABLE": "1",
        "LORA_APRS_HOST": os.environ["LORA_APRS_HOST"],
        "LORA_APRS_PORT": os.environ["LORA_APRS_PORT"],
    })

    # 3. Update runtime state
    lora_st = state.decoder_status["lora_aprs"]
    lora_st["enabled"] = True


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
    lora_st = state.decoder_status.get("lora_aprs") or {}
    settings["lora_aprs"] = {
        "enabled": bool(lora_st.get("enabled", False)),
        "available": _gr_lora_sdr_available(),
        "connected": bool(lora_st.get("connected", False)),
        "address": lora_st.get("address"),
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

    if "lora_aprs" in payload:
        from app.api.decoders import _start_lora_aprs_loop, _stop_lora_aprs_loop
        import asyncio
        lora = payload.get("lora_aprs") or {}
        lora_enabled = bool(lora.get("enabled", False))
        lora_st = state.decoder_status.get("lora_aprs") or {}
        currently_enabled = bool(lora_st.get("enabled", False))
        if lora_enabled and not currently_enabled:
            _ensure_lora_aprs_config()
            asyncio.create_task(_start_lora_aprs_loop(force=True))
        elif not lora_enabled and currently_enabled:
            asyncio.create_task(_stop_lora_aprs_loop())
            state.decoder_status["lora_aprs"]["enabled"] = False
        existing["lora_aprs"] = {"enabled": lora_enabled}

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
