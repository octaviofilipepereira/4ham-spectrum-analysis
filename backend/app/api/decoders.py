# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-23
# Decoders API endpoints

"""
Decoders API
============
Mode decoder control and event ingestion endpoints.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional
import asyncio

import numpy as np
from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import state
from app.dependencies.auth import optional_verify_basic_auth
from app.dependencies.helpers import (
    log,
    touch_decoder_source,
    record_decoder_event_saved,
    record_decoder_event_invalid,
)
from app.decoders.ingest import build_callsign_event
from app.decoders.parsers import parse_aprs_line, parse_cw_text, parse_ssb_asr_text


router = APIRouter()

# Queue that receives IQ chunks from the engine's pump loop.
# Created/registered in _start_ft_external_decoder, cleared in _stop.
_ft_external_iq_queue: Optional[asyncio.Queue] = None

# CW decoder IQ queue
_cw_iq_queue: Optional[asyncio.Queue] = None


def _refresh_decoder_process_status():
    """Update decoder process status from running instances."""
    if state.direwolf_process:
        state.decoder_status["direwolf_kiss"]["process_running"] = state.direwolf_process.returncode is None
        state.decoder_status["direwolf_kiss"]["process_pid"] = state.direwolf_process.pid
    
    if state.ft_internal_decoder:
        state.decoder_status["internal_native"]["ft_internal_status"] = state.ft_internal_decoder.snapshot()
    
    if state.ft_external_decoder:
        state.decoder_status["external_ft"]["ft_external_status"] = state.ft_external_decoder.snapshot()
    
    if state.cw_decoder:
        state.decoder_status["cw"]["status"] = state.cw_decoder.snapshot()


def _ingest_callsign_payloads(items: List[Dict], defaults: Dict) -> Dict:
    """
    Ingest and save callsign events to database.
    
    Args:
        items: List of event dicts
        defaults: Default values to merge with each event
        
    Returns:
        Dict with saved count and errors list
    """
    saved = 0
    errors = []
    
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append({"index": idx, "error": "invalid_event"})
            record_decoder_event_invalid()
            continue
        
        # Merge defaults with item
        payload = dict(defaults)
        payload.update(item)
        
        # Use scan center frequency if event has no frequency
        if payload.get("frequency_hz") in (None, 0, "0", ""):
            center_hz = state.scan_engine.center_hz or state.spectrum_cache.get("center_hz")
            if center_hz:
                payload["frequency_hz"] = int(center_hz)
        
        # Build and validate event
        event = build_callsign_event(payload, state.scan_state)
        if not event:
            errors.append({"index": idx, "error": "invalid_event"})
            record_decoder_event_invalid()
            continue
        
        # Only save events during active scan (not in preview or stopped mode)
        if state.scan_state.get("state") != "running":
            continue
        
        # Filter events by selected decoder mode (case-insensitive)
        event_mode = str(event.get("mode", "")).strip().upper()
        selected_mode = str(state.scan_state.get("decoder_mode", "")).strip().upper()
        if selected_mode and event_mode != selected_mode:
            continue  # Ignore events from different decoder modes
        
        # Save event
        touch_decoder_source(event.get("source"))
        state.db.insert_callsign(event)
        record_decoder_event_saved(event)
        saved += 1
    
    return {"status": "ok", "saved": saved, "errors": errors}


def _default_ft_internal_status() -> Dict:
    """Get default FT internal decoder status."""
    return {
        "enabled": False,
        "running": False,
        "modes": list(state.ft_internal_modes),
        "min_confidence": state.ft_internal_min_confidence,
        "poll_s": 1.0,
        "emit_mock_events": state.ft_internal_emit_mock_events,
        "mock_interval_s": state.ft_internal_mock_interval_s,
        "mock_callsign": state.ft_internal_mock_callsign,
        "started_at": None,
        "stopped_at": None,
        "last_heartbeat_at": None,
        "last_event_at": None,
        "events_emitted": 0,
        "last_error": None,
    }


def _get_ft_internal_frequency_hz() -> int:
    """Get current scan center frequency for FT decoder."""
    center_hz = state.scan_engine.center_hz or state.spectrum_cache.get("center_hz")
    if center_hz:
        return int(center_hz)
    return None


def _handle_ft_internal_event(payload: Dict) -> Dict:
    """Handle event from internal FT decoder."""
    return _ingest_callsign_payloads([payload], {"source": "internal_ft"})


async def _start_ft_internal_decoder(force: bool = False) -> Dict:
    """
    Start internal FT decoder.
    
    Args:
        force: Force start even if disabled in config
        
    Returns:
        Dict with started status and reason
    """
    if not force and not state.ft_internal_enable:
        state.decoder_status["internal_native"]["ft_internal_status"] = _default_ft_internal_status()
        return {"started": False, "reason": "ft_internal_disabled"}

    # Initialize decoder if needed
    if state.ft_internal_decoder is None:
        from app.decoders.ft_internal import InternalFtDecoder
        
        state.ft_internal_decoder = InternalFtDecoder(
            modes=state.ft_internal_modes,
            min_confidence=state.ft_internal_min_confidence,
            poll_s=1.0,
            emit_mock_events=state.ft_internal_emit_mock_events,
            mock_interval_s=state.ft_internal_mock_interval_s,
            mock_callsign=state.ft_internal_mock_callsign,
            on_event=_handle_ft_internal_event,
            frequency_provider=_get_ft_internal_frequency_hz,
            logger=log,
        )

    started = await state.ft_internal_decoder.start()
    state.decoder_status["internal_native"]["ft_internal_status"] = state.ft_internal_decoder.snapshot()
    return {"started": bool(started), "reason": None}


async def _stop_ft_internal_decoder() -> Dict:
    """
    Stop internal FT decoder.
    
    Returns:
        Dict with stopped status and reason
    """
    if state.ft_internal_decoder is None:
        state.decoder_status["internal_native"]["ft_internal_status"] = _default_ft_internal_status()
        return {"stopped": False, "reason": "ft_internal_not_running"}

    await state.ft_internal_decoder.stop()
    state.decoder_status["internal_native"]["ft_internal_status"] = state.ft_internal_decoder.snapshot()
    state.ft_internal_decoder = None
    return {"stopped": True, "reason": None}


def _handle_ft_external_event(payload: Dict) -> Dict:
    """Handle event from external FT decoder."""
    return _ingest_callsign_payloads([payload], {"source": "internal_ft_external"})


def _ft_external_flush_iq() -> None:
    """Drain stale IQ samples at the start of each decode window.

    Called by ExternalFtDecoder via on_window_start so that each window
    starts with fresh IQ instead of processing samples that accumulated
    during the previous decode phase.
    """
    if _ft_external_iq_queue is None:
        return
    drained = 0
    while True:
        try:
            _ft_external_iq_queue.get_nowait()
            drained += 1
        except asyncio.QueueEmpty:
            break


def _ft_external_iq_provider(num_samples: int):
    """Provide IQ samples from the engine's fan-out queue (non-blocking).

    Returns None when no chunk is available; the caller sleeps briefly
    and retries, yielding control to the event loop.
    """
    if _ft_external_iq_queue is None:
        return None
    try:
        return _ft_external_iq_queue.get_nowait()
    except asyncio.QueueEmpty:
        return None


def _ft_external_sample_rate_provider() -> int:
    """Get current scan sample rate."""
    return state.scan_engine.sample_rate


def _ft_external_frequency_provider() -> int:
    """Get current scan center frequency."""
    return state.scan_engine.center_hz or 0


def _ft_external_band_provider() -> str:
    """Get current scan band."""
    if state.scan_engine.config:
        return str(state.scan_engine.config.get("band", "")).strip().lower()
    return ""


def _ft_external_scan_park(dial_hz: int):
    """Hold scanner on specific frequency during decode."""
    if state.scan_engine.running and state.scan_engine.device:
        state.scan_engine.park(int(dial_hz))


def _ft_external_scan_unpark():
    """Resume normal scanning after decode."""
    if state.scan_engine.running:
        state.scan_engine.unpark()


async def _start_ft_external_decoder(force: bool = False) -> Dict:
    """
    Start external FT decoder.
    
    Args:
        force: Force start even if disabled in config
        
    Returns:
        Dict with started status and reason
    """
    global _ft_external_iq_queue

    if not force and not state.ft_external_enable:
        state.decoder_status["external_ft"]["ft_external_status"] = None
        return {"started": False, "reason": "ft_external_disabled"}

    # Create the IQ queue and register it with the engine's pump loop.
    # maxsize=2048 ≈ 8 s of IQ at 4096 chunks / 2048 kHz sample rate;
    # large enough to bridge a 15 s FT8 window, small enough to not OOM.
    if _ft_external_iq_queue is None:
        _ft_external_iq_queue = asyncio.Queue(maxsize=2048)
        state.scan_engine.register_iq_listener(_ft_external_iq_queue)

    # Initialize decoder if needed
    if state.ft_external_decoder is None:
        from app.decoders.ft_external import ExternalFtDecoder
        
        cmd_templates = {}
        if state.ft_external_command:
            cmd_templates["FT8"] = state.ft_external_command
            cmd_templates["FT4"] = state.ft_external_command
        if state.ft_external_command_wspr:
            cmd_templates["WSPR"] = state.ft_external_command_wspr

        output_formats = {"FT8": "jt9", "FT4": "jt9", "WSPR": "wsprd"}

        state.ft_external_decoder = ExternalFtDecoder(
            command_template=state.ft_external_command,
            command_templates=cmd_templates,
            output_format="jt9",
            output_formats=output_formats,
            modes=list(state.ft_external_modes),
            window_seconds={"FT8": 15.0, "FT4": 7.5, "WSPR": 120.0},
            poll_s=0.25,
            decode_timeout_s=20.0,
            iq_chunk_size=4096,
            iq_provider=_ft_external_iq_provider,
            sample_rate_provider=_ft_external_sample_rate_provider,
            frequency_provider=_ft_external_frequency_provider,
            band_provider=_ft_external_band_provider,
            on_event=_handle_ft_external_event,
            on_window_start=_ft_external_flush_iq,
            scan_park=_ft_external_scan_park,
            scan_unpark=_ft_external_scan_unpark,
            logger=log,
            target_sample_rate=state.ft_external_target_sr,
            wspr_every_n=state.ft_external_wspr_every_n,
        )

    started = await state.ft_external_decoder.start()
    state.decoder_status["external_ft"]["ft_external_status"] = state.ft_external_decoder.snapshot()
    return {"started": bool(started), "reason": None}


async def _stop_ft_external_decoder() -> Dict:
    """
    Stop external FT decoder.
    
    Returns:
        Dict with stopped status and reason
    """
    global _ft_external_iq_queue

    if _ft_external_iq_queue is not None:
        state.scan_engine.unregister_iq_listener(_ft_external_iq_queue)
        _ft_external_iq_queue = None

    if state.ft_external_decoder is None:
        state.decoder_status["external_ft"]["ft_external_status"] = None
        return {"stopped": False, "reason": "ft_external_not_running"}

    await state.ft_external_decoder.stop()
    state.decoder_status["external_ft"]["ft_external_status"] = state.ft_external_decoder.snapshot()
    state.ft_external_decoder = None
    return {"stopped": True, "reason": None}


# ───────────────────────────────────────────────────────────────────
# CW Decoder
# ───────────────────────────────────────────────────────────────────

def _handle_cw_event(payload: Dict) -> Dict:
    """Handle event from CW decoder."""
    # Inject a waterfall marker so the decode is visible on the spectrogram
    import time as _time
    freq_hz = int(payload.get("frequency_hz") or 0)
    if freq_hz > 0:
        bucket = int(round(freq_hz / 500)) * 500  # 500 Hz bucket
        state.cw_marker_cache[bucket] = {
            "frequency_hz": freq_hz,
            "offset_hz": int(payload.get("df_hz") or 0),
            "mode": "CW",
            "snr_db": float(payload.get("snr_db") or 0.0),
            "bandwidth_hz": 200,
            "confidence": float(payload.get("confidence") or 0.0),
            "seen_at": _time.time(),
        }
    return _ingest_callsign_payloads([payload], {"source": "internal_cw"})


def _cw_iq_provider(num_samples: int) -> Optional[np.ndarray]:
    """Provide IQ samples from the CW fan-out queue (non-blocking).

    Returns None when no chunk is available; the caller sleeps briefly
    and retries, yielding control to the event loop.
    """
    if _cw_iq_queue is None:
        return None
    try:
        return _cw_iq_queue.get_nowait()
    except asyncio.QueueEmpty:
        return None


def _cw_sample_rate_provider() -> int:
    """Get current scan sample rate."""
    return state.scan_engine.sample_rate


def _cw_frequency_provider() -> int:
    """Get current scan center frequency."""
    return state.scan_engine.center_hz or 0


async def _start_cw_decoder(force: bool = False) -> Dict:
    """
    Start CW decoder.
    
    Args:
        force: Force start even if disabled in config
        
    Returns:
        Dict with started status and reason
    """
    global _cw_iq_queue
    
    if not force and not state.cw_internal_enable:
        state.decoder_status["cw"]["status"] = None
        return {"started": False, "reason": "cw_disabled"}
    
    # Create the IQ queue and register it with the engine's pump loop
    if _cw_iq_queue is None:
        _cw_iq_queue = asyncio.Queue(maxsize=512)
        state.scan_engine.register_iq_listener(_cw_iq_queue)
    
    # Initialize decoder if needed
    if state.cw_decoder is None:
        from app.decoders.cw_session import CWDecoderSession
        
        state.cw_decoder = CWDecoderSession(
            iq_provider=_cw_iq_provider,
            sample_rate_provider=_cw_sample_rate_provider,
            frequency_provider=_cw_frequency_provider,
            on_event=_handle_cw_event,
            logger=log,
            target_sample_rate=state.cw_target_sample_rate,
            window_seconds=state.cw_window_seconds,
            overlap_seconds=state.cw_overlap_seconds,
            min_confidence=state.cw_min_confidence,
        )
    
    started = await state.cw_decoder.start()
    state.decoder_status["cw"]["status"] = state.cw_decoder.snapshot()

    # Freeze the scan sweep while CW is active.
    # CW decoding requires a continuous audio window (≥5 s) at a single
    # fixed frequency.  If the engine is sweeping (step_hz > 0) and jumps
    # to a new centre every dwell_ms=250 ms, the IQ buffer contains 20+
    # different carriers that the decoder cannot resolve.  Parking keeps
    # the SDR on the current centre_hz for the duration of the CW session.
    if state.scan_engine.running and state.scan_engine.step_hz > 0:
        state.scan_engine.park(state.scan_engine.center_hz)
        log(f"cw_scan_parked at {state.scan_engine.center_hz} Hz")

    return {"started": bool(started), "reason": None}


async def _stop_cw_decoder() -> Dict:
    """
    Stop CW decoder.
    
    Returns:
        Dict with stopped status and reason
    """
    global _cw_iq_queue
    
    if _cw_iq_queue is not None:
        state.scan_engine.unregister_iq_listener(_cw_iq_queue)
        _cw_iq_queue = None
    
    if state.cw_decoder is None:
        state.decoder_status["cw"]["status"] = None
        return {"stopped": False, "reason": "cw_not_running"}
    
    await state.cw_decoder.stop()
    state.decoder_status["cw"]["status"] = state.cw_decoder.snapshot()
    state.cw_decoder = None

    # Resume band sweep if it was frozen when CW started
    if state.scan_engine.running:
        state.scan_engine.unpark()
        log("cw_scan_unparked")

    return {"stopped": True, "reason": None}


# ═══════════════════════════════════════════════════════════════════
# API Endpoints
# ═══════════════════════════════════════════════════════════════════

@router.get("/status")
def decoder_status(_: bool = Depends(optional_verify_basic_auth)) -> Dict:
    """
    Get decoder status overview.
    
    Returns status for all decoders including internal/external FT,
    Direwolf KISS, and supported modes/sources.
    
    Returns:
        Comprehensive decoder status dict
    """
    _refresh_decoder_process_status()
    return {
        "ingest": {
            "endpoint": "/api/decoders/events",
            "batch": True
        },
        "supported_modes": ["FT8", "FT4", "APRS", "CW", "SSB", "Unknown"],
        "sources": ["direwolf", "cw", "asr", "dsp", "internal_ft", "external_ft", "internal_cw", "internal_ssb", "internal_psk"],
        "status": state.decoder_status
    }


@router.get("/internal-ft/status")
def decoder_internal_ft_status(_: bool = Depends(optional_verify_basic_auth)) -> Dict:
    """Get internal FT decoder status."""
    _refresh_decoder_process_status()
    return {
        "status": "ok",
        "decoder": state.decoder_status["internal_native"]["ft_internal_status"],
    }


@router.post("/internal-ft/start")
async def decoder_internal_ft_start(_: bool = Depends(optional_verify_basic_auth)) -> Dict:
    """Start internal FT decoder."""
    result = await _start_ft_internal_decoder(force=True)
    return {
        "status": "ok",
        "started": bool(result.get("started")),
        "reason": result.get("reason"),
        "decoder": state.decoder_status["internal_native"]["ft_internal_status"],
    }


@router.post("/internal-ft/stop")
async def decoder_internal_ft_stop(_: bool = Depends(optional_verify_basic_auth)) -> Dict:
    """Stop internal FT decoder."""
    result = await _stop_ft_internal_decoder()
    return {
        "status": "ok",
        "stopped": bool(result.get("stopped")),
        "reason": result.get("reason"),
        "decoder": state.decoder_status["internal_native"]["ft_internal_status"],
    }


@router.get("/external-ft/status")
def decoder_external_ft_status(_: bool = Depends(optional_verify_basic_auth)) -> Dict:
    """Get external FT decoder status."""
    snap = state.ft_external_decoder.snapshot() if state.ft_external_decoder else None
    state.decoder_status["external_ft"]["ft_external_status"] = snap
    return {
        "status": "ok",
        "decoder": snap,
    }


@router.post("/external-ft/start")
async def decoder_external_ft_start(_: bool = Depends(optional_verify_basic_auth)) -> Dict:
    """Start external FT decoder."""
    result = await _start_ft_external_decoder(force=True)
    return {
        "status": "ok",
        "started": bool(result.get("started")),
        "reason": result.get("reason"),
        "decoder": state.decoder_status["external_ft"]["ft_external_status"],
    }


@router.post("/external-ft/stop")
async def decoder_external_ft_stop(_: bool = Depends(optional_verify_basic_auth)) -> Dict:
    """Stop external FT decoder."""
    result = await _stop_ft_external_decoder()
    return {
        "status": "ok",
        "stopped": bool(result.get("stopped")),
        "reason": result.get("reason"),
        "decoder": state.decoder_status["external_ft"]["ft_external_status"],
    }


@router.post("/external-ft/modes")
async def decoder_external_ft_modes(payload: dict, _: bool = Depends(optional_verify_basic_auth)) -> Dict:
    """
    Update external FT decoder modes.
    
    Args:
        payload: Dict with 'modes' list
        
    Returns:
        Updated modes list
        
    Raises:
        HTTPException: 400 if modes invalid
    """
    modes = payload.get("modes")
    if not modes or not isinstance(modes, list):
        raise HTTPException(status_code=400, detail="modes must be a non-empty list")
    
    if state.ft_external_decoder:
        updated = state.ft_external_decoder.set_modes(modes)
        state.decoder_status["external_ft"]["ft_external_status"] = state.ft_external_decoder.snapshot()
        return {"status": "ok", "modes": updated}
    
    return {"status": "ok", "modes": [], "reason": "ft_external_not_running"}


@router.post("/cw/start")
async def decoder_cw_start(_: bool = Depends(optional_verify_basic_auth)) -> Dict:
    """Start CW decoder."""
    result = await _start_cw_decoder(force=True)
    return {
        "status": "ok",
        "started": bool(result.get("started")),
        "reason": result.get("reason"),
        "decoder": state.decoder_status["cw"]["status"],
    }


@router.post("/cw/stop")
async def decoder_cw_stop(_: bool = Depends(optional_verify_basic_auth)) -> Dict:
    """Stop CW decoder."""
    result = await _stop_cw_decoder()
    return {
        "status": "ok",
        "stopped": bool(result.get("stopped")),
        "reason": result.get("reason"),
        "decoder": state.decoder_status["cw"]["status"],
    }


@router.post("/events")
def decoder_events(payload: dict, _: bool = Depends(optional_verify_basic_auth)) -> Dict:
    """
    Ingest decoder events (batch or single).
    
    Args:
        payload: Event dict or dict with 'events' list
        
    Returns:
        Dict with saved count and errors
    """
    items = payload.get("events")
    if items is None:
        items = [payload.get("event", payload)]
    return _ingest_callsign_payloads(items, payload)


@router.post("/aprs")
def decoder_aprs(payload: dict, _: bool = Depends(optional_verify_basic_auth)) -> Dict:
    """
    Ingest APRS text lines.
    
    Args:
        payload: Dict with 'lines' list or single 'line'
        
    Returns:
        Dict with saved count and errors
    """
    lines = payload.get("lines")
    if lines is None:
        lines = [payload.get("line", "")]
    
    events = []
    for line in lines:
        parsed = parse_aprs_line(line)
        if parsed:
            events.append(parsed)
        else:
            events.append({"raw": str(line).strip(), "mode": "APRS"})
    
    return _ingest_callsign_payloads(events, payload)


@router.post("/cw")
def decoder_cw(payload: dict, _: bool = Depends(optional_verify_basic_auth)) -> Dict:
    """
    Ingest CW text.
    
    Args:
        payload: Dict with 'texts' list or single 'text'
        
    Returns:
        Dict with saved count and errors
    """
    texts = payload.get("texts")
    if texts is None:
        texts = [payload.get("text", "")]
    
    events = []
    for text in texts:
        parsed = parse_cw_text(text)
        if parsed:
            events.append(parsed)
        else:
            events.append({"raw": str(text).strip(), "mode": "CW"})
    
    return _ingest_callsign_payloads(events, payload)


@router.post("/ssb")
def decoder_ssb(payload: dict, _: bool = Depends(optional_verify_basic_auth)) -> Dict:
    """
    Ingest SSB/voice text (from ASR).
    
    Args:
        payload: Dict with 'texts' list or single 'text'
        
    Returns:
        Dict with saved count and errors
    """
    texts = payload.get("texts")
    if texts is None:
        texts = [payload.get("text", "")]
    
    events = []
    for text in texts:
        parsed = parse_ssb_asr_text(text)
        if parsed:
            events.append(parsed)
        else:
            events.append({"raw": str(text).strip(), "mode": "SSB"})
    
    return _ingest_callsign_payloads(events, payload)


@router.post("/start/{decoder_type}")
async def decoder_start(
    decoder_type: str,
    _: bool = Depends(optional_verify_basic_auth)
) -> Dict:
    """
    Start a specific decoder by type.
    
    Unified start endpoint that routes to appropriate decoder.
    
    Args:
        decoder_type: Decoder type ('internal-ft', 'external-ft', 'direwolf')
        
    Returns:
        Dict with start status and decoder info
        
    Raises:
        HTTPException: 400 if decoder type unknown
    """
    decoder_type = decoder_type.lower().strip()
    
    if decoder_type in ("internal-ft", "internal_ft", "ft-internal", "ft_internal"):
        result = await _start_ft_internal_decoder(force=True)
        return {
            "status": "ok",
            "decoder_type": "internal-ft",
            "started": bool(result.get("started")),
            "reason": result.get("reason"),
            "decoder": state.decoder_status["internal_native"]["ft_internal_status"],
        }
    
    elif decoder_type in ("external-ft", "external_ft", "ft-external", "ft_external"):
        result = await _start_ft_external_decoder(force=True)
        return {
            "status": "ok",
            "decoder_type": "external-ft",
            "started": bool(result.get("started")),
            "reason": result.get("reason"),
            "decoder": state.decoder_status["external_ft"]["ft_external_status"],
        }
    
    elif decoder_type == "cw":
        result = await _start_cw_decoder(force=True)
        return {
            "status": "ok",
            "decoder_type": "cw",
            "started": bool(result.get("started")),
            "reason": result.get("reason"),
            "decoder": state.decoder_status["cw"]["status"],
        }
    
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown decoder type: {decoder_type}. Supported: internal-ft, external-ft, cw"
        )


@router.post("/stop/{decoder_type}")
async def decoder_stop(
    decoder_type: str,
    _: bool = Depends(optional_verify_basic_auth)
) -> Dict:
    """
    Stop a specific decoder by type.
    
    Unified stop endpoint that routes to appropriate decoder.
    
    Args:
        decoder_type: Decoder type ('internal-ft', 'external-ft', 'direwolf')
        
    Returns:
        Dict with stop status and decoder info
        
    Raises:
        HTTPException: 400 if decoder type unknown
    """
    decoder_type = decoder_type.lower().strip()
    
    if decoder_type in ("internal-ft", "internal_ft", "ft-internal", "ft_internal"):
        result = await _stop_ft_internal_decoder()
        return {
            "status": "ok",
            "decoder_type": "internal-ft",
            "stopped": bool(result.get("stopped")),
            "reason": result.get("reason"),
            "decoder": state.decoder_status["internal_native"]["ft_internal_status"],
        }
    
    elif decoder_type in ("external-ft", "external_ft", "ft-external", "ft_external"):
        result = await _stop_ft_external_decoder()
        return {
            "status": "ok",
            "decoder_type": "external-ft",
            "stopped": bool(result.get("stopped")),
            "reason": result.get("reason"),
            "decoder": state.decoder_status["external_ft"]["ft_external_status"],
        }
    
    elif decoder_type == "cw":
        result = await _stop_cw_decoder()
        return {
            "status": "ok",
            "decoder_type": "cw",
            "stopped": bool(result.get("stopped")),
            "reason": result.get("reason"),
            "decoder": state.decoder_status["cw"]["status"],
        }
    
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown decoder type: {decoder_type}. Supported: internal-ft, external-ft, cw"
        )

