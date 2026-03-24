# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-24 12:00:00 UTC
# Global application state

"""
Application State Management
=============================
Central repository for all global application state variables.
"""

import asyncio
import collections
import os
from pathlib import Path
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
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DATA_DIR = Path(os.getenv("DATA_DIR", str(_PROJECT_ROOT / "data"))).expanduser()
_DB_PATH = Path(os.getenv("EVENTS_DB_PATH", str(_DATA_DIR / "events.sqlite"))).expanduser()
_EXPORT_DIR = Path(os.getenv("EXPORT_DIR", str(_DATA_DIR / "exports"))).expanduser()

_DATA_DIR.mkdir(parents=True, exist_ok=True)
_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

db = Database(str(_DB_PATH))
export_manager = ExportManager(
    export_dir=str(_EXPORT_DIR),
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
    "ft4": False,
    "wspr": False,
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

# CW decode markers: bucket_key (500 Hz) -> {frequency_hz, offset_hz, mode, snr_db, crest_db, bandwidth_hz, confidence, seen_at}
cw_marker_cache: dict = {}

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
marker_min_snr_db = _env_float("MARKER_MIN_SNR_DB", 8.0)
marker_min_confidence = _env_float("MARKER_MIN_CONFIDENCE", 0.55)
marker_min_hits = _env_int("MARKER_MIN_HITS", 2)
marker_max_age_s = _env_float("MARKER_MAX_AGE_S", 30.0)  # Allow markers to persist across 2+ scan cycles

# SSB false-positive control: only persist/visualize SSB traffic above this confidence.
ssb_traffic_min_confidence = _env_float("SSB_TRAFFIC_MIN_CONFIDENCE", 0.55)


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

# CW decoder
cw_internal_enable = _env_bool("CW_INTERNAL_ENABLE", False)
cw_target_sample_rate = _env_int("CW_TARGET_SAMPLE_RATE", 8000)
cw_window_seconds = _env_float("CW_WINDOW_SECONDS", 5.0)
cw_overlap_seconds = _env_float("CW_OVERLAP_SECONDS", 2.0)
cw_min_confidence = _env_float("CW_MIN_CONFIDENCE", 0.3)
cw_sweep_step_hz = _env_int("CW_SWEEP_STEP_HZ", 6500)
cw_sweep_dwell_s = _env_float("CW_SWEEP_DWELL_S", 30.0)
cw_sweep_settle_ms = _env_int("CW_SWEEP_SETTLE_MS", 100)
cw_marker_ttl_s = _env_float("CW_MARKER_TTL_S", 45.0)

# Other decoders
ssb_internal_enable = _env_bool("SSB_INTERNAL_ENABLE", True)
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
        "min_bw_hz": min_bw_hz,
        "ssb_traffic_min_confidence": ssb_traffic_min_confidence,
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
    "cw": {
        "enabled": cw_internal_enable,
        "target_sample_rate": cw_target_sample_rate,
        "window_seconds": cw_window_seconds,
        "overlap_seconds": cw_overlap_seconds,
        "min_confidence": cw_min_confidence,
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
cw_decoder = None


# ═══════════════════════════════════════════════════════════════════
# Logs and Cache
# ═══════════════════════════════════════════════════════════════════

# deque(maxlen=500): O(1) append+discard vs list.pop(0) O(n).
# Supports len() and iteration; use list(logs) for slicing.
logs: collections.deque = collections.deque(maxlen=500)

count_cache = {
    "timestamp": 0.0,
    "value": 0,
    "key": None
}


# ═══════════════════════════════════════════════════════════════════
# Authentication
# ═══════════════════════════════════════════════════════════════════

# Env-var credentials serve as an emergency fallback only. DB credentials
# take precedence when present. Set AUTH_REQUIRED=0 to force-disable auth.
_env_auth_user = os.getenv("BASIC_AUTH_USER")
_env_auth_pass = os.getenv("BASIC_AUTH_PASS")

def _load_auth_from_db():
    """Load auth credentials from DB, falling back to env vars.

    Returns a tuple (user, pass_or_hash, is_hashed, required).
    """
    _auth_required_env = os.getenv("AUTH_REQUIRED", "1").strip().lower()
    _force_disabled = _auth_required_env in ("0", "false", "no")

    _db_cfg = db.get_auth_config()
    _db_user = _db_cfg.get("auth_user") or ""
    _db_hash = _db_cfg.get("auth_pass_hash") or ""
    _db_enabled = bool(_db_cfg.get("auth_enabled"))

    if _db_enabled and _db_user and _db_hash:
        # DB credentials take precedence
        return _db_user, _db_hash, True, True

    if (not _force_disabled) and _env_auth_user and _env_auth_pass:
        _hashed = is_bcrypt_hash(_env_auth_pass)
        return _env_auth_user, _env_auth_pass, _hashed, (not _force_disabled)

    return None, None, None, False


auth_user, auth_pass, auth_pass_is_hashed, auth_required = _load_auth_from_db()


def reload_auth_from_db() -> None:
    """Re-read auth credentials from DB and update module-level globals.

    Call this after saving or clearing credentials via the API so that the
    running process picks up the change without a restart.
    """
    global auth_user, auth_pass, auth_pass_is_hashed, auth_required
    auth_user, auth_pass, auth_pass_is_hashed, auth_required = _load_auth_from_db()


# ═══════════════════════════════════════════════════════════════════
# Event Retention Configuration
# ═══════════════════════════════════════════════════════════════════

# Maximum event age in days; 0 disables age-based purge
retention_days = int(os.getenv("RETENTION_DAYS", "30"))

# Maximum total events across both tables; 0 disables count-based purge
retention_max_events = int(os.getenv("MAX_EVENTS", "500000"))

# When max_events is reached: export ALL and keep only this many (most recent)
retention_keep_events = int(os.getenv("RETENTION_KEEP_EVENTS", "50000"))

# Export events to CSV automatically before purging
_retention_auto_env = os.getenv("RETENTION_AUTO_EXPORT", "1").strip().lower()
retention_auto_export = _retention_auto_env not in ("0", "false", "no")

# Populated by the retention background task; consumed once by ws_status broadcast
retention_notification = None


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


def verify_auth_transport(auth_header: str = None, cookie_header: str = None) -> bool:
    """Verify either a session cookie or legacy Basic Auth header."""
    from app.dependencies.auth import verify_session_cookie_header

    if verify_session_cookie_header(cookie_header):
        return True
    return verify_basic_auth_header(auth_header)

