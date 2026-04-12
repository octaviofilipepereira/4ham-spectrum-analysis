# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-23 21:30 UTC
# Admin API endpoints

"""
Admin API
=========
Administrative operations and device setup endpoints.
"""

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, BackgroundTasks, Depends

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

# Repo root: backend/app/api/admin.py → ../../../../
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


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


@router.get("/audio/detect")
def admin_audio_detect(_: None = Depends(verify_basic_auth)) -> Dict:
    """
    Detect audio devices and configuration.
    
    Probes audio system for available devices, capabilities, and
    recommends optimal configuration.
    
    Returns:
        Audio detection report with:
            - devices: List of detected audio devices
            - recommended: Suggested audio configuration
            - capabilities: Supported sample rates, channels
            - system: Audio system info (ALSA, PulseAudio, PipeWire)
    """
    audio_probe = probe_audio_setup()
    
    return {
        "status": "ok",
        "audio": audio_probe,
        "suggested_config": audio_probe.get("suggested"),
    }


@router.post("/retention/run")
async def run_retention_now(_: None = Depends(verify_basic_auth)) -> Dict:
    """
    Manually trigger event retention.

    Runs one retention cycle immediately: identifies purgeable events,
    exports them to CSV (if RETENTION_AUTO_EXPORT=1), then deletes them.

    Returns:
        Result dict with purged count, export info, and download URL.
    """
    from app.core.retention import run_retention
    import time
    from app.dependencies import state as _state
    notification = await run_retention()
    _state.db.set_kv("last_retention_run", str(time.time()))
    return {
        "status": "ok",
        "result": notification if notification else {
            "purged": 0,
            "exported": False,
            "export_id": None,
            "export_rows": 0,
            "download_url": None,
        },
    }


@router.get("/update/check")
def admin_update_check(_: None = Depends(verify_basic_auth)) -> Dict:
    """
    Check if software updates are available via git.

    Fetches from origin and compares local HEAD with remote.

    Returns:
        Dict with up_to_date flag, commits_behind count, branch name,
        and list of pending commit messages.
    """
    if not command_exists("git"):
        return {"status": "error", "error": "git not found in PATH"}

    branch_result = run_command(
        ["git", "-C", str(_REPO_ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
        timeout=10,
    )
    branch = (branch_result.get("stdout") or "main").strip()
    if branch in ("HEAD", ""):
        branch = "main"

    fetch_result = run_command(
        ["git", "-C", str(_REPO_ROOT), "fetch", "origin", branch],
        timeout=30,
    )
    if fetch_result.get("returncode") != 0:
        return {
            "status": "error",
            "error": "git fetch failed: " + (fetch_result.get("stderr") or "").strip(),
        }

    count_result = run_command(
        ["git", "-C", str(_REPO_ROOT), "rev-list", f"HEAD..origin/{branch}", "--count"],
        timeout=10,
    )
    try:
        commits_behind = int((count_result.get("stdout") or "0").strip())
    except ValueError:
        commits_behind = 0

    commit_log: List[str] = []
    if commits_behind > 0:
        log_result = run_command(
            [
                "git", "-C", str(_REPO_ROOT),
                "log", f"HEAD..origin/{branch}",
                "--oneline", "--no-merges",
            ],
            timeout=10,
        )
        commit_log = [
            line for line in (log_result.get("stdout") or "").splitlines() if line.strip()
        ]

    return {
        "status": "ok",
        "up_to_date": commits_behind == 0,
        "commits_behind": commits_behind,
        "branch": branch,
        "commit_log": commit_log,
    }


@router.post("/update/apply")
async def admin_update_apply(
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_basic_auth),
) -> Dict:
    """
    Apply pending software updates via git pull.

    Runs git pull, detects which files changed, and determines whether
    a service restart is required (any backend Python file changed).
    If a restart is needed it is scheduled via BackgroundTasks so the
    HTTP response is delivered before the process is replaced.

    Returns:
        Dict with updated flag, head hashes, files_changed list,
        restart_required flag, and raw pull output.
    """
    if not command_exists("git"):
        return {"status": "error", "error": "git not found in PATH"}

    head_before = (
        run_command(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
            timeout=10,
        ).get("stdout") or ""
    ).strip()

    pull_result = run_command(
        ["git", "-C", str(_REPO_ROOT), "pull"],
        timeout=60,
    )
    if pull_result.get("returncode") != 0:
        return {
            "status": "error",
            "error": "git pull failed: " + (pull_result.get("stderr") or "").strip(),
        }

    head_after = (
        run_command(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
            timeout=10,
        ).get("stdout") or ""
    ).strip()

    updated = head_before != head_after
    files_changed: List[str] = []
    restart_required = False
    deps_installed: Dict = {"pip": None, "npm": None}

    if updated and head_before:
        diff_result = run_command(
            ["git", "-C", str(_REPO_ROOT), "diff", head_before, head_after, "--name-only"],
            timeout=10,
        )
        files_changed = [
            f for f in (diff_result.get("stdout") or "").splitlines() if f.strip()
        ]
        restart_required = any(f.startswith("backend/") for f in files_changed)

        # Install new Python dependencies if requirements.txt changed
        if any(f == "backend/requirements.txt" for f in files_changed):
            venv_pip = _REPO_ROOT / ".venv" / "bin" / "pip"
            req_file = _REPO_ROOT / "backend" / "requirements.txt"
            if venv_pip.is_file() and req_file.is_file():
                pip_result = run_command(
                    [str(venv_pip), "install", "--quiet", "-r", str(req_file)],
                    timeout=120,
                )
                deps_installed["pip"] = pip_result.get("returncode") == 0

        # Install new frontend dependencies if package.json changed
        if any(f == "frontend/package.json" for f in files_changed):
            frontend_dir = _REPO_ROOT / "frontend"
            if (frontend_dir / "package.json").is_file() and command_exists("npm"):
                npm_result = run_command(
                    ["npm", "--prefix", str(frontend_dir), "install", "--no-fund", "--no-audit"],
                    timeout=120,
                )
                deps_installed["npm"] = npm_result.get("returncode") == 0

    if restart_required:
        background_tasks.add_task(_schedule_restart)

    return {
        "status": "ok",
        "updated": updated,
        "head_before": head_before[:12] if head_before else None,
        "head_after": head_after[:12] if head_after else None,
        "files_changed": files_changed,
        "restart_required": restart_required,
        "deps_installed": deps_installed,
        "pull_output": (pull_result.get("stdout") or "").strip(),
    }


async def _schedule_restart() -> None:
    """Restart the server via scripts/server_control.sh (fully detached).

    Uses a UNIX double-fork so the restart process is re-parented to PID 1
    and survives the shutdown of the current process tree.  This works
    regardless of whether the server is managed by systemd or started
    manually.
    """
    import logging

    logger = logging.getLogger("admin")

    script = _REPO_ROOT / "scripts" / "server_control.sh"
    if not script.is_file():
        logger.error("server_control.sh not found at %s — cannot auto-restart", script)
        return

    if not hasattr(os, "fork"):
        logger.error("os.fork unavailable on this platform — cannot auto-restart")
        return

    await asyncio.sleep(3)
    logger.info("Initiating server restart via %s", script)

    pid = os.fork()
    if pid == 0:
        # ── first child ──────────────────────────────────────────
        try:
            os.setsid()
            pid2 = os.fork()
            if pid2 == 0:
                # ── grandchild (fully detached, ppid → 1) ────────
                devnull = os.open(os.devnull, os.O_RDWR)
                for fd in (0, 1, 2):
                    os.dup2(devnull, fd)
                if devnull > 2:
                    os.close(devnull)
                os.execvp(
                    "bash",
                    ["bash", "-c", f'sleep 1; exec "{script}" restart'],
                )
            else:
                os._exit(0)
        except Exception:
            os._exit(1)
    else:
        os.waitpid(pid, 0)
