# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-23 21:30 UTC
# Global application state

"""
Application State Management
=============================
Central repository for all global application state variables.
"""

import asyncio
import os
from datetime import datetime, timezone

from app.scan.engine import ScanEngine
from app.sdr.controller import SDRController
from app.storage.db import Database
from app.storage.exporter import ExportManager
from app.core.auth import is_bcrypt_hash


# ═══════════════════════════════════════════════════════════════════
# Environment Variable Helpers
# ═══════════════════════════════════════════════════════════════════

def _env_int(key: str, default: int) -> int:
    """Parse integer from environment string."""
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    """Parse float from environment string."""
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    """Parse boolean from environment string."""
    value = os.getenv(key, "").lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _env_csv(key: str, default: list) -> list:
    """Parse CSV from environment string."""
    value = os.getenv(key)
    if not value:
        return default
    return [item.strip().upper() for item in value.split(",") if item.strip()]


# ═══════════════════════════════════════════════════════════════════
# Core Application Components
# ═══════════════════════════════════════════════════════════════════

controller = SDRController()
scan_engine = ScanEngine(controller)

# Database and export manager
os.makedirs("data", exist_ok=True)
db = Database("data/events.sqlite")
export_manager = ExportManager(
    export_dir="data/exports",
    db=db,
    max_files=_env_int("EXPORT_MAX_FILES", 50),
    max_age_days=_env_int("EXPORT_MAX_AGE_DAYS", 7),
)


# ═══════════════════════════════════════════════════════════════════
# Scan State
# ═══════════════════════════════════════════════════════════════════

scan_state = {
    "state": "stopped",
    "device": None,
    "started_at": None,
    "scan": None,
    "scan_id": None
}


# ═══════════════════════════════════════════════════════════════════
# Default Configuration
# ═══════════════════════════════════════════════════════════════════

default_modes = {
    "ft8": False,
    "aprs": False,
    "cw": False,
    "ssb": True,
}


def default_settings_payload():
    """Return default settings payload."""
    return {
        "modes": dict(default_modes),
        "summary": {"showBand": True, "showMode": True},
    }


# ═══════════════════════════════════════════════════════════════════
# Spectrum and DSP State
# ═══════════════════════════════════════════════════════════════════

spectrum_cache = {
    "fft_db": None,
    "bin_hz": None,
    "min_db": None,
    "max_db": None,
    "timestamp": None,
    "center_hz": 0,
    "span_hz": 0
}

noise_floor = {}
last_frame_ts = None
last_send_ts = None

agc_state = {}
last_agc_gain_db = None

# Tracking dict: bucket_key -> {"hits": int, "last_seen": float, "marker": dict}
marker_candidates = {}

threshold_state = {}


# ═══════════════════════════════════════════════════════════════════
# DSP Configuration
# ═══════════════════════════════════════════════════════════════════

agc_enabled = os.getenv("DSP_AGC_ENABLE", "0").lower() in {"1", "true", "yes", "on"}
agc_target_rms = _env_float("DSP_AGC_TARGET_RMS", 0.25)
agc_max_gain_db = _env_float("DSP_AGC_MAX_GAIN_DB", 30.0)
agc_alpha = _env_float("DSP_AGC_ALPHA", 0.2)
snr_threshold_db = _env_float("DSP_SNR_THRESHOLD_DB", 6.0)
min_bw_hz = _env_int("DSP_MIN_BW_HZ", 500)

# Mode marker quality gate
marker_min_snr_db = _env_float("MARKER_MIN_SNR_DB", 10.0)
marker_min_confidence = _env_float("MARKER_MIN_CONFIDENCE", 0.55)
marker_min_hits = _env_int("MARKER_MIN_HITS", 2)
marker_max_age_s = _env_float("MARKER_MAX_AGE_S", 10.0)


# ═══════════════════════════════════════════════════════════════════
# WebSocket Configuration
# ═══════════════════════════════════════════════════════════════════

ws_spectrum_fps = max(1.0, _env_float("WS_SPECTRUM_FPS", 5.0))
ws_send_timeout_s = max(0.01, _env_float("WS_SEND_TIMEOUT_S", 0.1))
ws_compress_spectrum = _env_bool("WS_COMPRESS_SPECTRUM", True)
ws_protocol_version = "1.1"

spectrum_send_stats = {"sent": 0, "dropped": 0}


# ═══════════════════════════════════════════════════════════════════
# Decoder Configuration
# ═══════════════════════════════════════════════════════════════════

# Internal FT decoder
ft_internal_enable = _env_bool("FT_INTERNAL_ENABLE", False)
ft_internal_modes = _env_csv("FT_INTERNAL_MODES", ["FT8", "FT4"])
ft_internal_min_confidence = _env_float("FT_INTERNAL_MIN_CONFIDENCE", 0.0)
ft_internal_emit_mock_events = _env_bool("FT_INTERNAL_EMIT_MOCK_EVENTS", False)
ft_internal_mock_interval_s = max(0.25, _env_float("FT_INTERNAL_MOCK_INTERVAL_S", 15.0))
ft_internal_mock_callsign = str(os.getenv("FT_INTERNAL_MOCK_CALLSIGN", "N0CALL")).strip().upper() or "N0CALL"

# External FT decoder (jt9 / wsprd)
ft_external_enable = _env_bool("FT_EXTERNAL_ENABLE", False)
ft_external_modes = _env_csv("FT_EXTERNAL_MODES", ["FT8", "FT4"])
ft_external_command = str(os.getenv(
    "FT_EXTERNAL_COMMAND",
    "jt9 {mode_flag} -p {period_int} -d 3 -a . -t . {wav_path}"
)).strip()
ft_external_command_wspr = str(os.getenv(
    "FT_EXTERNAL_COMMAND_WSPR",
    "wsprd -d -f {frequency_mhz} {wav_path}"
)).strip()
ft_external_target_sr = _env_int("FT_EXTERNAL_TARGET_SAMPLE_RATE", 12000)
ft_external_wspr_every_n = _env_int("FT_EXTERNAL_WSPR_EVERY_N", 5)

# Other decoders
cw_internal_enable = _env_bool("CW_INTERNAL_ENABLE", False)
ssb_internal_enable = _env_bool("SSB_INTERNAL_ENABLE", False)
psk_internal_enable = _env_bool("PSK_INTERNAL_ENABLE", False)


# ═══════════════════════════════════════════════════════════════════
# Decoder Runtime State
# ═══════════════════════════════════════════════════════════════════

decoder_runtime_metrics = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "callsign_saved": 0,
    "invalid_events": 0,
    "by_source": {},
    "by_mode": {},
}

decoder_status = {
    "sources": {},
    "direwolf_kiss": {
        "enabled": _env_bool("DIREWOLF_KISS_ENABLE", False),
        "address": None,
        "connected": False,
        "last_packet_at": None,
        "last_error": None,
        "autostart": _env_bool("DIREWOLF_AUTOSTART", False),
        "process_running": False,
        "process_pid": None
    },
    "files": {
        "aprs": None,
        "cw": None,
        "ssb": None
    },
    "dsp": {
        "agc_enabled": agc_enabled,
        "agc_target_rms": agc_target_rms,
        "agc_max_gain_db": agc_max_gain_db,
        "agc_alpha": agc_alpha,
        "snr_threshold_db": snr_threshold_db,
        "min_bw_hz": min_bw_hz
    },
    "internal_native": {
        "ft_internal_enable": ft_internal_enable,
        "ft_internal_modes": ft_internal_modes,
        "ft_internal_min_confidence": ft_internal_min_confidence,
        "ft_internal_emit_mock_events": ft_internal_emit_mock_events,
        "ft_internal_mock_interval_s": ft_internal_mock_interval_s,
        "ft_internal_mock_callsign": ft_internal_mock_callsign,
        "cw_internal_enable": cw_internal_enable,
        "ssb_internal_enable": ssb_internal_enable,
        "psk_internal_enable": psk_internal_enable,
        "ft_internal_status": {
            "enabled": False,
            "running": False,
            "modes": ft_internal_modes,
            "min_confidence": ft_internal_min_confidence,
        },
        "ft_external_status": None,
    },
    "external_ft": {
        "enabled": ft_external_enable,
        "modes": ft_external_modes,
        "command": ft_external_command,
        "command_wspr": ft_external_command_wspr,
        "target_sample_rate": ft_external_target_sr,
        "status": None
    },
    "runtime": decoder_runtime_metrics,
}

# Decoder tasks and processes
decoder_tasks = []
decoder_stop = asyncio.Event()
kiss_task = None
direwolf_process = None
ft_internal_decoder = None
ft_external_decoder = None


# ═══════════════════════════════════════════════════════════════════
# Logs and Cache
# ═══════════════════════════════════════════════════════════════════

logs = []

count_cache = {
    "timestamp": 0.0,
    "value": 0,
    "key": None
}


# ═══════════════════════════════════════════════════════════════════
# Authentication
# ═══════════════════════════════════════════════════════════════════

auth_user = os.getenv("BASIC_AUTH_USER")
auth_pass = os.getenv("BASIC_AUTH_PASS")
auth_pass_is_hashed = None
if auth_pass:
    auth_pass_is_hashed = is_bcrypt_hash(auth_pass)

# AUTH_REQUIRED env var acts as a global on/off switch.
# When set to 0, false or no, authentication is disabled even if credentials
# are configured in .env. Defaults to True when credentials are present.
_auth_required_env = os.getenv("AUTH_REQUIRED", "1").strip().lower()
auth_required = (_auth_required_env not in ("0", "false", "no")) and bool(auth_user and auth_pass)


def verify_basic_auth_header(auth_header: str) -> bool:
    """
    Verify HTTP Basic Authentication header.
    
    Supports both bcrypt-hashed and plaintext passwords (legacy).
    
    Args:
        auth_header: Authorization header value (e.g., "Basic dXNlcjpwYXNz")
        
    Returns:
        True if authentication succeeds, False otherwise
    """
    from app.core.auth import parse_basic_auth, verify_password
    
    if not auth_user or not auth_pass:
        return False
    
    if not auth_header:
        return False
    
    # Parse credentials from header
    credentials = parse_basic_auth(auth_header)
    if not credentials:
        return False
    
    username, password = credentials
    
    # Check username
    if username != auth_user:
        return False
    
    # Verify password (supports both hashed and plaintext)
    if auth_pass_is_hashed:
        # Password is hashed - use bcrypt verification
        return verify_password(password, auth_pass)
    else:
        # Password is plaintext - direct comparison (legacy)
        # SECURITY WARNING: Plaintext passwords are not secure!
        # Run 'python scripts/hash_password.py' to generate a hash
        return password == auth_pass

