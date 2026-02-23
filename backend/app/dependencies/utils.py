# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Utility functions

"""
Utility Functions
=================
Common utility functions for system operations, device detection, etc.
"""

import os
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

from app.sdr.controller import soapy_import_status
from app.dependencies import state


def command_exists(command: str) -> bool:
    """Check if a command exists in PATH."""
    return shutil.which(command) is not None


def run_command(command: List[str], timeout: int = 180) -> Dict:
    """
    Run a shell command and return its output.
    
    Args:
        command: List of command parts
        timeout: Command timeout in seconds
        
    Returns:
        Dict with command, returncode, stdout, stderr
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "command": " ".join(command),
            "returncode": result.returncode,
            "stdout": (result.stdout or "")[-4000:],
            "stderr": (result.stderr or "")[-4000:],
        }
    except Exception as exc:
        return {
            "command": " ".join(command),
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
        }


def is_apt_package_installed(package_name: str) -> bool:
    """Check if an APT package is installed (Linux only)."""
    result = run_command(["dpkg-query", "-W", "-f=${Status}", package_name], timeout=30)
    if result.get("returncode") != 0:
        return False
    status_text = (result.get("stdout") or "").strip().lower()
    return "install ok installed" in status_text


def check_apt_packages(packages: List[str]) -> Dict:
    """
    Check which APT packages are installed.
    
    Returns:
        Dict with 'installed' and 'missing' lists
    """
    installed = []
    missing = []
    for package_name in packages:
        if is_apt_package_installed(package_name):
            installed.append(package_name)
        else:
            missing.append(package_name)
    return {"installed": installed, "missing": missing}


def list_audio_devices_from_pactl(kind: str) -> List[str]:
    """List audio devices using pactl (PulseAudio)."""
    result = run_command(["pactl", "list", "short", kind], timeout=15)
    if result.get("returncode") != 0:
        return []
    devices = []
    for line in (result.get("stdout") or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1].strip():
            devices.append(parts[1].strip())
    return devices


def parse_default_pactl_endpoint(info_text: str, label: str) -> Optional[str]:
    """Parse default PulseAudio endpoint from pactl info output."""
    for line in (info_text or "").splitlines():
        if line.startswith(label):
            return line.split(":", 1)[1].strip()
    return None


def list_audio_devices_from_alsa(command: str) -> List[str]:
    """List audio devices using ALSA commands (arecord/aplay)."""
    result = run_command([command, "-L"], timeout=15)
    if result.get("returncode") != 0:
        return []
    devices = []
    for line in (result.get("stdout") or "").splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        if line[:1].isspace() or line.startswith("\t"):
            continue
        devices.append(item)
    return devices


def probe_audio_setup() -> Dict:
    """
    Probe system audio configuration.
    
    Returns:
        Dict with detected audio devices and suggested config
    """
    inputs = []
    outputs = []
    default_input = None
    default_output = None
    methods = []

    if command_exists("pactl"):
        methods.append("pactl")
        info = run_command(["pactl", "info"], timeout=15)
        info_text = info.get("stdout") or ""
        default_input = parse_default_pactl_endpoint(info_text, "Default Source")
        default_output = parse_default_pactl_endpoint(info_text, "Default Sink")
        inputs = list_audio_devices_from_pactl("sources")
        outputs = list_audio_devices_from_pactl("sinks")

    if not inputs and command_exists("arecord"):
        methods.append("arecord")
        inputs = list_audio_devices_from_alsa("arecord")
    if not outputs and command_exists("aplay"):
        methods.append("aplay")
        outputs = list_audio_devices_from_alsa("aplay")

    suggested = {
        "input_device": default_input or (inputs[0] if inputs else ""),
        "output_device": default_output or (outputs[0] if outputs else ""),
        "sample_rate": 48000,
        "rx_gain": 1,
        "tx_gain": 1,
    }
    return {
        "methods": methods,
        "inputs": inputs,
        "outputs": outputs,
        "default_input": default_input,
        "default_output": default_output,
        "suggested": suggested,
    }


def normalize_device_choice(choice: str) -> str:
    """Normalize device type choice to standard names."""
    value = str(choice or "").strip().lower()
    if "rtl" in value:
        return "rtl"
    if "hack" in value:
        return "hackrf"
    if "air" in value:
        return "airspy"
    if not value:
        return "other"
    return value


def find_device_by_choice(devices: List[Dict], choice: str) -> Optional[Dict]:
    """Find a device in list by fuzzy matching choice string."""
    term = str(choice or "").lower()
    for item in devices:
        haystack = " ".join([
            str(item.get("id", "")).lower(),
            str(item.get("type", "")).lower(),
            str(item.get("name", "")).lower(),
        ])
        if term in haystack:
            return item
    return None


def device_profile(choice: str) -> Dict:
    """Get default configuration profile for device type."""
    profiles = {
        "rtl": {
            "sample_rate": 2048000,
            "gain": 30,
            "ppm_correction": 0,
            "frequency_offset_hz": 0,
            "gain_profile": "auto",
        },
        "hackrf": {
            "sample_rate": 2000000,
            "gain": 20,
            "ppm_correction": 0,
            "frequency_offset_hz": 0,
            "gain_profile": "auto",
        },
        "airspy": {
            "sample_rate": 2500000,
            "gain": 20,
            "ppm_correction": 0,
            "frequency_offset_hz": 0,
            "gain_profile": "auto",
        },
        "other": {
            "sample_rate": 48000,
            "gain": 20,
            "ppm_correction": 0,
            "frequency_offset_hz": 0,
            "gain_profile": "auto",
        },
    }
    return profiles.get(choice, profiles["other"])


def device_requirements(choice: str) -> Dict:
    """Get system requirements for device type."""
    linux_packages = ["python3-soapysdr", "soapysdr-tools", "libsoapysdr-dev"]
    if choice == "rtl":
        linux_packages.extend(["soapysdr-module-rtlsdr", "rtl-sdr"])
    elif choice == "hackrf":
        linux_packages.extend(["soapysdr-module-hackrf", "hackrf"])
    elif choice == "airspy":
        linux_packages.extend(["soapysdr-module-airspy", "airspy"])
    else:
        linux_packages.append("soapysdr-module-all")
    return {
        "python_modules": ["SoapySDR"],
        "linux_apt_packages": linux_packages,
        "required_commands": ["SoapySDRUtil", "rtl_test", "lsusb"],
    }


def probe_device_setup(choice: str) -> Dict:
    """
    Probe SDR device setup and requirements.
    
    Args:
        choice: Device type choice
        
    Returns:
        Dict with detected devices, requirements, and status
    """
    devices = state.controller.list_devices()
    matched = find_device_by_choice(devices, choice)
    soapy_import, soapy_error = soapy_import_status()

    requirements = device_requirements(choice)
    apt_status = {"installed": [], "missing": []}
    if sys.platform.startswith("linux"):
        apt_status = check_apt_packages(requirements.get("linux_apt_packages", []))

    return {
        "platform": sys.platform,
        "commands": {
            "SoapySDRUtil": command_exists("SoapySDRUtil"),
            "rtl_test": command_exists("rtl_test"),
            "lsusb": command_exists("lsusb"),
        },
        "python": {
            "soapy_import_ok": soapy_import,
            "soapy_import_error": soapy_error,
        },
        "apt_packages": apt_status,
        "devices_detected": devices,
        "match_found": bool(matched),
        "matched_device": matched,
    }


def run_linux_auto_install(choice: str, missing_packages: Optional[List[str]] = None) -> Dict:
    """
    Attempt automatic installation of missing packages on Linux.
    
    Tries multiple privilege escalation strategies:
    1. Direct root (if running as root)
    2. sudo without password
    3. pkexec with GUI prompt
    
    Args:
        choice: Device type choice
        missing_packages: List of missing package names
        
    Returns:
        Dict with installation results:
            - attempted: Whether installation was attempted
            - success: Whether all packages installed successfully
            - error: Error code if failed
            - method: Privilege escalation method used
            - steps: List of command execution results
    """
    attempted = False
    steps = []

    if not sys.platform.startswith("linux"):
        return {
            "attempted": False,
            "success": False,
            "error": "auto_install_only_supported_on_linux",
            "method": None,
            "steps": steps,
        }

    base_packages = list(missing_packages or [])
    if not base_packages:
        return {
            "attempted": False,
            "success": True,
            "error": None,
            "method": None,
            "steps": steps,
        }

    # Try different privilege escalation strategies
    strategies = []
    
    # Strategy 1: Direct root access
    if command_exists("apt-get") and hasattr(os, "geteuid") and os.geteuid() == 0:
        strategies.append({
            "name": "root_direct",
            "commands": [
                ["apt-get", "update"],
                ["apt-get", "install", "-y", *base_packages],
            ],
        })
    
    # Strategy 2: sudo without password
    if command_exists("sudo"):
        strategies.append({
            "name": "sudo_nopasswd",
            "commands": [
                ["sudo", "-n", "apt-get", "update"],
                ["sudo", "-n", "apt-get", "install", "-y", *base_packages],
            ],
        })
    
    # Strategy 3: pkexec with GUI
    if command_exists("pkexec"):
        strategies.append({
            "name": "pkexec_gui",
            "commands": [
                ["pkexec", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "update"],
                ["pkexec", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", *base_packages],
            ],
        })

    if not strategies:
        return {
            "attempted": False,
            "success": False,
            "error": "no_privilege_escalation_tool",
            "method": None,
            "steps": steps,
        }

    # Try each strategy until one succeeds
    for strategy in strategies:
        strategy_ok = True
        for command in strategy["commands"]:
            attempted = True
            result = run_command(command, timeout=900)
            result["strategy"] = strategy["name"]
            steps.append(result)
            if result.get("returncode") != 0:
                strategy_ok = False
                break
        
        if strategy_ok:
            return {
                "attempted": attempted,
                "success": True,
                "error": None,
                "method": strategy["name"],
                "steps": steps,
            }

    # Check if failure was due to authentication
    combined_stderr = "\n".join((item.get("stderr") or "") for item in steps).lower()
    needs_elevation = any(token in combined_stderr for token in [
        "password is required",
        "authentication",
        "polkit",
        "not authorized",
        "not allowed",
        "permission denied",
    ])

    return {
        "attempted": attempted,
        "success": False,
        "error": "elevation_required" if needs_elevation else "apt_install_failed",
        "method": None,
        "steps": steps,
    }
