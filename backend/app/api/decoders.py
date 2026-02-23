# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Decoders API endpoints

"""
Decoders API
============
Mode decoder control and event ingestion endpoints.
"""

from datetime import datetime, timezone
from typing import Dict, List

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


def _refresh_decoder_process_status():
    """Update decoder process status from running instances."""
    if state.direwolf_process:
        state.decoder_status["direwolf_kiss"]["process_running"] = state.direwolf_process.returncode is None
        state.decoder_status["direwolf_kiss"]["process_pid"] = state.direwolf_process.pid
    
    if state.ft_internal_decoder:
        state.decoder_status["internal_native"]["ft_internal_status"] = state.ft_internal_decoder.snapshot()
    
    if state.ft_external_decoder:
        state.decoder_status["external_ft"]["ft_external_status"] = state.ft_external_decoder.snapshot()


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


def _ft_external_iq_provider(num_samples: int):
    """Provide IQ samples from scan engine (blocking)."""
    if not state.scan_engine.running:
        return None
    return state.scan_engine.read_iq(num_samples)


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
    if not force and not state.ft_external_enable:
        state.decoder_status["external_ft"]["ft_external_status"] = None
        return {"started": False, "reason": "ft_external_disabled"}

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
    if state.ft_external_decoder is None:
        state.decoder_status["external_ft"]["ft_external_status"] = None
        return {"stopped": False, "reason": "ft_external_not_running"}

    await state.ft_external_decoder.stop()
    state.decoder_status["external_ft"]["ft_external_status"] = state.ft_external_decoder.snapshot()
    state.ft_external_decoder = None
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
