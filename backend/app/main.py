# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-23 21:30 UTC

"""
4ham Spectrum Analysis - Main Application Entry Point
======================================================

FastAPI application with modular architecture:
- REST API endpoints organized by domain (health, events, scan, settings, etc.)
- WebSocket handlers for real-time streaming
- Rate limiting and security middleware
- CORS configuration
- Static file serving for frontend
"""

import os
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Configure logging with rotation BEFORE any other imports that use logging
from app.log_config import setup_logging
setup_logging()
from app.version import APP_VERSION

# Import API and WebSocket routers
from app.api import health, events, scan, settings, logs, exports, admin, decoders, map as map_api, auth as auth_api, analytics, features as features_api, external_mirrors as external_mirrors_api, satellite as satellite_api, beacons as beacons_api
from app.websocket import logs as ws_logs, events as ws_events, spectrum as ws_spectrum, status as ws_status, satellite as ws_satellite, beacons as ws_beacons
from app.core import features as _features


# ═══════════════════════════════════════════════════════════════════
# Application Lifespan: auto-start configured decoders
# ═══════════════════════════════════════════════════════════════════

_log = logging.getLogger("uvicorn.error")


async def _retention_loop():
    """Background task: run retention every 24 h, skipping startup run if <24 h since last run."""
    import time
    await asyncio.sleep(10)  # allow server to finish startup
    while True:
        try:
            from app.core.retention import run_retention
            from app.dependencies import state as _state
            _RETENTION_KV_KEY = "last_retention_run"
            _24H = 86400
            last_ts = _state.db.get_kv(_RETENTION_KV_KEY)
            elapsed = time.time() - float(last_ts) if last_ts else _24H
            if elapsed < _24H:
                remaining = int(_24H - elapsed)
                _log.info("Retention: skipping startup run, last run %.1f h ago (next in %d h %02d min)",
                          elapsed / 3600, remaining // 3600, (remaining % 3600) // 60)
                await asyncio.sleep(remaining)
                continue
            await run_retention()
            _state.db.set_kv(_RETENTION_KV_KEY, str(time.time()))
        except Exception as exc:
            _log.warning("Retention task error: %s", exc)
        await asyncio.sleep(_24H)


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Auto-start enabled decoders on startup and stop them gracefully on shutdown."""
    from app.dependencies import state as _state
    from app.api.decoders import _start_ft_external_decoder, _start_ft_internal_decoder, _start_cw_decoder, _start_kiss_loop, _stop_kiss_loop

    # Restore ASR enabled/disabled state from DB settings
    try:
        from app.decoders.ssb_asr import set_asr_enabled
        _saved = _state.db.get_settings()
        _asr_cfg = (_saved.get("asr") or {})
        _asr_on = bool(_asr_cfg.get("enabled", True))
        set_asr_enabled(_asr_on)
        _log.info("ASR startup: enabled=%s (from DB settings)", _asr_on)
    except Exception as exc:
        _log.warning("ASR startup config restore failed: %s", exc)

    if _state.ft_external_enable:
        try:
            result = await _start_ft_external_decoder(force=False)
            _log.info("FT external decoder startup: %s", result)
        except Exception as exc:
            _log.warning("FT external decoder startup failed: %s", exc)

    if _state.ft_internal_enable:
        try:
            result = await _start_ft_internal_decoder(force=False)
            _log.info("FT internal decoder startup: %s", result)
        except Exception as exc:
            _log.warning("FT internal decoder startup failed: %s", exc)

    if _state.cw_internal_enable:
        try:
            result = await _start_cw_decoder(force=False)
            _log.info("CW decoder startup: %s", result)
        except Exception as exc:
            _log.warning("CW decoder startup failed: %s", exc)

    # Auto-start KISS/APRS loop if Direwolf KISS is configured
    if _state.decoder_status["direwolf_kiss"]["enabled"]:
        try:
            result = await _start_kiss_loop(force=False)
            _log.info("KISS loop startup: %s", result)
        except Exception as exc:
            _log.warning("KISS loop startup failed: %s", exc)

    # Auto-start LoRa-APRS UDP listener — gated by FEATURE_LORA_APRS feature
    # flag (default off). When the feature is disabled, the entire LoRa
    # subsystem stays dormant: no UDP listener, no settings exposure, no UI.
    if _features.lora_aprs_enabled() and _state.decoder_status["lora_aprs"]["enabled"]:
        try:
            from app.api.decoders import _start_lora_aprs_loop
            result = await _start_lora_aprs_loop(force=False)
            _log.info("LoRa APRS loop startup: %s", result)
        except Exception as exc:
            _log.warning("LoRa APRS loop startup failed: %s", exc)

    # Auto-open preview if a real SDR device is available
    try:
        sdr_devices = [
            d for d in _state.controller.list_devices()
            if str(d.get("type", "")).lower() not in ("audio",)
        ]
        if sdr_devices:
            preview_sr = int(os.getenv("PREVIEW_SAMPLE_RATE", "2048000"))
            preview_hz = int(os.getenv("PREVIEW_CENTER_HZ", "14175000"))
            # Band boundaries for the startup preview band (default: 20m).
            # These must be passed so spectrum.py uses exact band limits on the
            # ruler instead of falling back to center_hz ± sample_rate/2.
            preview_start = int(os.getenv("PREVIEW_START_HZ", "14000000"))
            preview_end = int(os.getenv("PREVIEW_END_HZ", "14350000"))
            opened = await _state.scan_engine.preview_open(
                device_id=sdr_devices[0]["id"],
                sample_rate=preview_sr,
                center_hz=preview_hz,
                start_hz=preview_start,
                end_hz=preview_end,
            )
            if opened:
                _state.scan_state["state"] = "preview"
                _log.info(
                    "SDR preview started: %s @ %.3f MHz",
                    sdr_devices[0]["id"],
                    preview_hz / 1e6,
                )
    except Exception as exc:
        _log.warning("SDR preview startup skipped: %s", exc)

    # Auto-start satellite scheduler if module is installed
    try:
        if _state.db.get_kv("satellite_module_installed") == "true":
            from app.satellite.lifecycle import start_scheduler as _sat_start
            await _sat_start()
            _log.info("Satellite scheduler auto-started (module installed).")
    except Exception as exc:
        _log.warning("Satellite scheduler auto-start failed: %s", exc)

    # Initialise beacon scheduler (always available; not auto-started)
    try:
        from app.beacons.scheduler import BeaconScheduler
        from app.websocket.beacons import broadcast_slot_start, broadcast_observation
        import asyncio as _asyncio

        async def _persist_and_broadcast_observation(obs: dict) -> None:
            try:
                loop = _asyncio.get_running_loop()
                await _asyncio.gather(
                    loop.run_in_executor(None, _state.db.insert_beacon_observation, obs),
                    broadcast_observation(obs),
                )
            except Exception:
                _log.exception("beacon observation persistence error")

        def _obs_cb(obs: dict) -> None:
            _asyncio.create_task(_persist_and_broadcast_observation(dict(obs)))

        def _slot_cb(callsign: str, freq_hz: int, slot_index: int, slot_start_utc: str) -> None:
            _asyncio.create_task(broadcast_slot_start(callsign, freq_hz, slot_index, slot_start_utc))

        # Create dedicated IQ queue for beacon scheduler (separate from FFT's _spectrum_queue).
        # This queue will be registered via scan_engine.register_iq_listener() when the
        # scheduler starts, ensuring the beacon monitor does NOT steal IQ chunks from the
        # waterfall/spectrum display.
        _engine = _state.scan_engine
        _state.beacon_iq_queue = _asyncio.Queue(maxsize=128)

        def _sample_rate_provider() -> int:
            if _engine is None:
                return 2048000
            return int(getattr(_engine, "sample_rate", 2048000) or 2048000)

        _state.beacon_scheduler = BeaconScheduler(
            iq_queue=_state.beacon_iq_queue,
            sample_rate_provider=_sample_rate_provider,
            scan_park=getattr(_engine, "park", None) if _engine else None,
            scan_unpark=getattr(_engine, "unpark", None) if _engine else None,
            on_observation=_obs_cb,
            on_slot_start=_slot_cb,
        )
        _log.info("Beacon scheduler initialised (not running — start via /api/beacons/start).")
    except Exception as exc:
        _log.warning("Beacon scheduler init failed: %s", exc)

    # Start retention background task
    asyncio.create_task(_retention_loop())

    # Start occupancy detection background task (independent of WS connections)
    from app.websocket.events import _run_occupancy_detection_loop
    asyncio.create_task(_run_occupancy_detection_loop())

    # Start ionospheric data refresh (Kp + SFI from NOAA SWPC, every 15 min)
    from app.core.ionospheric import ionospheric_refresh_loop
    asyncio.create_task(ionospheric_refresh_loop())

    # Start internet connectivity probe (TCP/53 to public anycast resolvers,
    # every 60 s).  Other modules (satellite TLE/catalog refresh, mirrors)
    # can call connectivity.is_online() to skip network round-trips when
    # offline instead of stalling on long timeouts.
    from app.core import connectivity as _connectivity
    _connectivity_task = asyncio.create_task(_connectivity.connectivity_loop())
    app_instance.state.connectivity_task = _connectivity_task

    # Initialise external mirrors subsystem (push-mode replication).
    try:
        from app.external_mirrors import (
            ExternalMirrorPusher,
            ExternalMirrorRepository,
            TokenCache,
        )
        from app.external_mirrors.token_vault import TokenVault
        from app.external_mirrors import registry as mirrors_registry
        _mirror_repo = ExternalMirrorRepository(_state.db)
        _mirror_vault = TokenVault.from_env()
        _vault_source = "MIRRORS_MASTER_KEY env"
        if _mirror_vault is None:
            from pathlib import Path as _Path
            _data_dir = _Path(_state.db.path).parent
            _mirror_vault = TokenVault.from_data_dir(_data_dir)
            _vault_source = f"{_data_dir}/.mirrors_master.key"
        _mirror_token_cache = TokenCache(
            repository=_mirror_repo, vault=_mirror_vault
        )
        if _mirror_vault is not None:
            n_loaded = _mirror_token_cache.load_persisted()
            _log.info(
                "External mirrors token vault enabled (%s); %d persisted token(s) loaded.",
                _vault_source,
                n_loaded,
            )
        else:
            _log.warning(
                "External mirrors token vault unavailable; tokens are memory-only "
                "(rotate-token required after each restart)."
            )
        _mirror_pusher = ExternalMirrorPusher(
            repo=_mirror_repo,
            token_cache=_mirror_token_cache,
        )
        mirrors_registry.init(_mirror_repo, _mirror_pusher, _mirror_token_cache)
        await _mirror_pusher.start()
        _log.info("External mirrors pusher started")
    except Exception as exc:
        _log.warning("External mirrors pusher failed to start: %s", exc)

    # Auto-start preset scheduler if there are enabled schedules
    try:
        enabled = [s for s in _state.db.get_preset_schedules() if s.get("enabled")]
        _sched_kv = _state.db.get_kv("preset_scheduler_enabled")
        if enabled and _sched_kv != "0":
            from app.scan.preset_scheduler import PresetScheduler
            from app.api.scan import _apply_preset_by_id, _stop_active_rotation
            scheduler = PresetScheduler(
                get_schedules=_state.db.get_preset_schedules,
                apply_preset_cb=_apply_preset_by_id,
                stop_rotation_cb=_stop_active_rotation,
                is_rotation_running=lambda: bool(_state.scan_rotation and _state.scan_rotation.running),
            )
            _state.preset_scheduler = scheduler
            await scheduler.start()
            _log.info("Preset scheduler auto-started (%d enabled schedules)", len(enabled))
    except Exception as exc:
        _log.warning("Preset scheduler auto-start failed: %s", exc)

    yield

    # Graceful shutdown
    try:
        from app.external_mirrors import registry as mirrors_registry
        if mirrors_registry.is_initialised():
            await mirrors_registry.get_pusher().stop()
    except Exception:
        pass
    if _state.preset_scheduler and _state.preset_scheduler.running:
        try:
            await _state.preset_scheduler.stop()
        except Exception:
            pass
    from app.api.decoders import _stop_ft_external_decoder, _stop_ft_internal_decoder
    if _state.ft_external_decoder:
        try:
            await _stop_ft_external_decoder()
        except Exception:
            pass
    if _state.ft_internal_decoder:
        try:
            await _stop_ft_internal_decoder()
        except Exception:
            pass
    if _state.kiss_task and not _state.kiss_task.done():
        try:
            await _stop_kiss_loop()
        except Exception:
            pass

    # Stop satellite scheduler gracefully
    try:
        from app.satellite.lifecycle import stop_scheduler as _sat_stop
        await _sat_stop()
    except Exception:
        pass

    # Stop beacon scheduler gracefully
    try:
        if _state.beacon_scheduler and _state.beacon_scheduler._running:
            await _state.beacon_scheduler.stop()
    except Exception:
        pass

    # Stop connectivity probe gracefully
    try:
        _ct = getattr(app_instance.state, "connectivity_task", None)
        if _ct and not _ct.done():
            _ct.cancel()
            try:
                await _ct
            except (asyncio.CancelledError, Exception):
                pass
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# FastAPI Application Setup
# ═══════════════════════════════════════════════════════════════════

app = FastAPI(
    title="4ham Spectrum Analysis",
    description="Real-time spectrum monitoring and digital mode decoding for amateur radio",
    version=APP_VERSION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# ═══════════════════════════════════════════════════════════════════
# Rate Limiting Configuration
# ═══════════════════════════════════════════════════════════════════

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

# ═══════════════════════════════════════════════════════════════════
# CORS Configuration
# ═══════════════════════════════════════════════════════════════════

# Configure allowed origins based on environment
cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")
cors_enabled = os.getenv("CORS_ENABLED", "1").lower() in {"1", "true", "yes", "on"}

if cors_enabled:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ═══════════════════════════════════════════════════════════════════
# Security Headers Middleware
# ═══════════════════════════════════════════════════════════════════

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all HTTP responses."""
    response = await call_next(request)
    
    # Security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    
    # Prevent stale frontend assets after a deploy. We send no-store on
    # ALL frontend resources (HTML, JS/MJS, CSS, JSON, MAPs, SVG) so the
    # browser never serves cached copies — every request hits the server
    # fresh. This is intentionally aggressive because deploys here are
    # frequent and stale modules have caused repeated user-facing bugs.
    # API responses and binary vendor assets keep their default behaviour.
    content_type = response.headers.get("content-type", "")
    path = request.url.path
    is_api = path.startswith("/api/") or path.startswith("/ws/")
    is_html = "text/html" in content_type
    is_frontend_asset = path.endswith((".js", ".mjs", ".css", ".json", ".map", ".svg", ".html"))
    if not is_api and (is_html or is_frontend_asset):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    
    # Remove server header to avoid information disclosure
    if "server" in response.headers:
        del response.headers["server"]
    
    return response

# ═══════════════════════════════════════════════════════════════════
# REST API Routers
# ═══════════════════════════════════════════════════════════════════

# Include all API routers with /api prefix
app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(auth_api.router, prefix="/api/auth", tags=["Auth"])
app.include_router(events.router, prefix="/api", tags=["Events"])
app.include_router(scan.router, prefix="/api/scan", tags=["Scan"])
app.include_router(settings.router, prefix="/api/settings", tags=["Settings"])
app.include_router(logs.router, prefix="/api", tags=["Logs"])
app.include_router(exports.router, prefix="/api", tags=["Exports"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(external_mirrors_api.router, prefix="/api/admin/mirrors", tags=["External Mirrors"])
app.include_router(decoders.router, prefix="/api/decoders", tags=["Decoders"])
app.include_router(map_api.router, prefix="/api", tags=["Map"])
app.include_router(analytics.router, prefix="/api", tags=["Analytics"])
app.include_router(features_api.router, prefix="/api/features", tags=["Features"])
app.include_router(satellite_api.router, prefix="/api/satellite", tags=["Satellite"])
app.include_router(beacons_api.router, prefix="/api/beacons", tags=["Beacons"])

# ═══════════════════════════════════════════════════════════════════
# WebSocket Routers
# ═══════════════════════════════════════════════════════════════════

# Include WebSocket handlers
app.include_router(ws_logs.router, tags=["WebSocket - Logs"])
app.include_router(ws_events.router, tags=["WebSocket - Events"])
app.include_router(ws_spectrum.router, tags=["WebSocket - Spectrum"])
app.include_router(ws_status.router, tags=["WebSocket - Status"])
app.include_router(ws_satellite.router, tags=["WebSocket - Satellite"])
app.include_router(ws_beacons.router, tags=["WebSocket - Beacons"])

# ═══════════════════════════════════════════════════════════════════
# Static File Serving (Frontend)
# ═══════════════════════════════════════════════════════════════════

# Serve frontend static files from /frontend directory
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

if FRONTEND_DIR.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(FRONTEND_DIR), html=True),
        name="frontend"
    )
