# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Admin API endpoints

"""
Admin API
=========
Administrative operations and device setup endpoints.
"""

from typing import Dict

from fastapi import APIRouter, Depends

from app.dependencies import state
from app.dependencies.auth import verify_basic_auth
from app.dependencies.utils import (
    normalize_device_choice,
    device_requirements,
    device_profile,
    probe_device_setup,
    probe_audio_setup,
    run_command,
    command_exists,
)
from app.sdr.controller import soapy_import_status


router = APIRouter()


@router.post("/reset-all-config")
def admin_reset_all_config(_: None = Depends(verify_basic_auth)) -> Dict:
    """
    Reset all configuration to defaults.
    
    Clears all settings, bands, and configuration from database.
    WARNING: This operation cannot be undone.
    
    Returns:
        Status dict
    """
    state.db.clear_configuration()
    return {"status": "ok"}


@router.post("/device/setup")
def admin_device_setup(payload: dict, _: None = Depends(verify_basic_auth)) -> Dict:
    """
    Automated device setup wizard.
    
    Detects SDR device, checks requirements, optionally installs missing packages,
    and applies recommended configuration.
    
    Args:
        payload: Setup configuration dict with keys:
            - device_type: Device type ('rtl', 'hackrf', 'airspy', etc.)
            - dry_run: If True, only probe without making changes
            - auto_install: If True, attempt to install missing packages
            - apply_config: If True, save detected config to database
            
    Returns:
        Comprehensive setup report dict with:
            - requirements: Required packages and commands
            - probe_before/after: Device detection results
            - install: Package installation results
            - audio_probe: Audio device detection
            - configured: Applied configuration
    """
    payload = payload or {}
    choice = normalize_device_choice(payload.get("device_type"))
    dry_run = bool(payload.get("dry_run", False))
    auto_install = bool(payload.get("auto_install", False))
    apply_config = bool(payload.get("apply_config", True))
    requirements = device_requirements(choice)

    # Probe device status before installation
    probe_before = probe_device_setup(choice)
    missing_packages_before = probe_before.get("apt_packages", {}).get("missing", [])
    
    install_result = {
        "attempted": False,
        "success": True,
        "error": None,
        "method": None,
        "steps": [],
    }

    # Auto-install missing packages if requested
    should_install = bool(missing_packages_before)
    if not dry_run and auto_install and should_install:
        from app.dependencies.utils import run_linux_auto_install
        install_result = run_linux_auto_install(choice, missing_packages=missing_packages_before)

    # Probe device status after installation
    probe_after = probe_device_setup(choice)
    matched = probe_after.get("matched_device")
    profile = device_profile(choice)
    audio_probe = probe_audio_setup()

    configured = {
        "applied": False,
        "device_id": None,
        "profile": profile,
        "device_config": None,
        "audio_config": audio_probe.get("suggested"),
    }
    
    # Apply configuration if requested and device detected
    if not dry_run and apply_config and matched:
        settings = state.db.get_settings()
        settings["device_id"] = matched.get("id")
        
        device_config = settings.get("device_config") or {}
        device_config["device_class"] = choice if choice in {"rtl", "hackrf", "airspy"} else "auto"
        device_config["ppm_correction"] = profile.get("ppm_correction", 0)
        device_config["frequency_offset_hz"] = profile.get("frequency_offset_hz", 0)
        device_config["gain_profile"] = profile.get("gain_profile", "auto")
        settings["device_config"] = device_config
        settings["audio_config"] = audio_probe.get("suggested")
        
        state.db.save_settings(settings)
        
        configured = {
            "applied": True,
            "device_id": matched.get("id"),
            "profile": profile,
            "device_config": device_config,
            "audio_config": audio_probe.get("suggested"),
        }

    return {
        "status": "ok",
        "device_type": choice,
        "dry_run": dry_run,
        "requirements": requirements,
        "missing_packages_before": missing_packages_before,
        "probe_before": probe_before,
        "install": install_result,
        "probe_after": probe_after,
        "audio_probe": audio_probe,
        "configured": configured,
    }


@router.post("/config/test")
def admin_config_test(payload: dict, _: None = Depends(verify_basic_auth)) -> Dict:
    """
    Test device and audio configuration.
    
    Validates device availability and audio configuration without making changes.
    
    Args:
        payload: Configuration to test with keys:
            - device_id: Device ID to test
            - audio_config: Audio config to validate (sample_rate, gains)
            
    Returns:
        Test results dict with device and audio validation status
    """
    payload = payload or {}

    selected_device_id = payload.get("device_id")
    audio_config = payload.get("audio_config") or {}

    # Test device availability
    devices = state.controller.list_devices()
    soapy_ok, soapy_error = soapy_import_status()
    device_ok = bool(devices)
    
    if selected_device_id:
        device_ok = any(str(item.get("id")) == str(selected_device_id) for item in devices)

    # Test audio configuration
    sample_rate = int(audio_config.get("sample_rate") or 0)
    rx_gain = float(audio_config.get("rx_gain") or 0)
    tx_gain = float(audio_config.get("tx_gain") or 0)
    
    audio_checks = {
        "arecord": command_exists("arecord"),
        "aplay": command_exists("aplay"),
        "pactl": command_exists("pactl"),
        "pw-cli": command_exists("pw-cli"),
        "sample_rate_valid": 8000 <= sample_rate <= 384000,
        "rx_gain_valid": 0.0 <= rx_gain <= 10.0,
        "tx_gain_valid": 0.0 <= tx_gain <= 10.0,
    }
    
    audio_ok = bool(
        audio_checks["sample_rate_valid"]
        and audio_checks["rx_gain_valid"]
        and audio_checks["tx_gain_valid"]
        and (audio_checks["arecord"] or audio_checks["pactl"] or audio_checks["pw-cli"])
        and (audio_checks["aplay"] or audio_checks["pactl"] or audio_checks["pw-cli"])
    )

    return {
        "status": "ok",
        "device": {
            "selected": selected_device_id,
            "ok": device_ok and soapy_ok,
            "detected_count": len(devices),
            "soapy_import_ok": soapy_ok,
            "soapy_import_error": soapy_error,
        },
        "audio": {
            "ok": audio_ok,
            "checks": audio_checks,
        },
    }
