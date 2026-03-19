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
import re

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import state
from app.dependencies.auth import optional_verify_basic_auth
from app.dependencies.helpers import (
    log,
    safe_float,
    hint_mode_by_frequency,
    touch_decoder_source,
    record_decoder_event_saved,
    record_decoder_event_invalid,
    is_plausible_occupancy_event,
)
from app.decoders.ingest import build_callsign_event
from app.decoders.parsers import parse_aprs_line, parse_cw_text, parse_ssb_asr_text
from app.dsp.pipeline import (
    apply_agc_smoothed,
    compute_power_db,
    estimate_occupancy,
    classify_mode_heuristic,
)


router = APIRouter()

# Queue that receives IQ chunks from the engine's pump loop.
# Created/registered in _start_ft_external_decoder, cleared in _stop.
_ft_external_iq_queue: Optional[asyncio.Queue] = None

# CW decoder IQ queue
_cw_iq_queue: Optional[asyncio.Queue] = None

# SSB detector IQ queue and task
_ssb_iq_queue: Optional[asyncio.Queue] = None
_ssb_detector_task: Optional[asyncio.Task] = None
_ssb_traffic_last_emit: Dict = {}

_SSB_TRAFFIC_KEYWORDS = {
    "CQ",
    "QRZ",
    "OVER",
    "COPY",
    "REPORT",
    "CALLING",
    "STATION",
    "CONTACT",
    "NAME",
    "QTH",
    "FIVE",
    "NINE",
    "73",
}


def _score_ssb_confirmed_event(event: Dict) -> float:
    score = 0.40
    parse_method = str(event.get("parse_method") or "").strip().lower()
    if parse_method == "direct":
        score += 0.30
    elif parse_method == "phonetic":
        score += 0.22
    if event.get("grid"):
        score += 0.10
    if event.get("report"):
        score += 0.10
    if event.get("frequency_hz"):
        score += 0.10
    return min(1.0, round(score, 3))


def _score_ssb_traffic_text(text: str) -> float:
    tokens = re.findall(r"[A-Za-z0-9]+", str(text).upper())
    score = 0.18
    if len(tokens) >= 3:
        score += 0.12
    if len(tokens) >= 6:
        score += 0.10
    if any(token in _SSB_TRAFFIC_KEYWORDS for token in tokens):
        score += 0.20
    if any(token.isdigit() for token in tokens):
        score += 0.08
    return min(0.68, round(score, 3))


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

    state.decoder_status["internal_native"]["ssb_internal_status"] = _snapshot_ssb_detector_status()


def _snapshot_ssb_detector_status() -> Dict:
    running = bool(_ssb_detector_task is not None and not _ssb_detector_task.done())
    queue_size = 0
    if _ssb_iq_queue is not None:
        try:
            queue_size = _ssb_iq_queue.qsize()
        except Exception:
            queue_size = 0
    return {
        "enabled": bool(state.ssb_internal_enable),
        "running": running,
        "queue_size": int(queue_size),
    }


def _update_noise_floor_ssb(band: str, power_db: float) -> float:
    alpha = 0.1
    current = state.noise_floor.get(band)
    if current is None:
        state.noise_floor[band] = power_db
        return power_db
    updated = alpha * power_db + (1 - alpha) * current
    state.noise_floor[band] = updated
    return updated


def _emit_ssb_traffic_event_from_occupancy(occupancy_event: Dict) -> None:
    if not isinstance(occupancy_event, dict):
        return

    if not occupancy_event.get("occupied"):
        return

    mode_name = str(occupancy_event.get("mode") or "").strip().upper()
    if mode_name != "SSB":
        return

    frequency_hz = int(safe_float(occupancy_event.get("frequency_hz"), 0.0) or 0)
    if frequency_hz <= 0:
        return

    now_ts = datetime.now(timezone.utc).timestamp()
    bucket_key = (
        str(occupancy_event.get("band") or ""),
        int(frequency_hz / 2000),
    )
    last_emit_ts = _ssb_traffic_last_emit.get(bucket_key, 0.0)
    if (now_ts - last_emit_ts) < 8.0:
        return
    _ssb_traffic_last_emit[bucket_key] = now_ts

    if len(_ssb_traffic_last_emit) > 4096:
        stale_before = now_ts - 120.0
        for key, value in list(_ssb_traffic_last_emit.items()):
            if value < stale_before:
                _ssb_traffic_last_emit.pop(key, None)

    base_confidence = float(safe_float(occupancy_event.get("confidence"), 0.35) or 0.35)
    snr_db = float(safe_float(occupancy_event.get("snr_db"), 0.0) or 0.0)
    snr_bonus = min(0.25, max(0.0, snr_db / 40.0))
    ssb_score = min(0.95, max(0.35, base_confidence + snr_bonus + 0.12))
    if ssb_score < float(getattr(state, "ssb_traffic_min_confidence", 0.78) or 0.78):
        return

    msg = f"SSB traffic candidate @ {frequency_hz / 1_000_000:.3f} MHz"
    payload = {
        "mode": "SSB_TRAFFIC",
        "callsign": "",
        "raw": msg,
        "msg": msg,
        "band": occupancy_event.get("band"),
        "frequency_hz": frequency_hz,
        "snr_db": occupancy_event.get("snr_db"),
        "power_dbm": occupancy_event.get("power_dbm"),
        "confidence": round(ssb_score, 3),
        "ssb_state": "SSB_TRAFFIC",
        "ssb_score": round(ssb_score, 3),
        "ssb_parse_method": "occupancy",
        "source": "internal_ssb_occupancy",
        "device": occupancy_event.get("device"),
        "scan_id": occupancy_event.get("scan_id"),
    }
    event = build_callsign_event(payload, state.scan_state)
    if not event:
        return

    state.db.insert_callsign(event)
    touch_decoder_source(event.get("source"))
    record_decoder_event_saved(event)


async def _run_ssb_detector_loop() -> None:
    global _ssb_iq_queue

    while True:
        try:
            if _ssb_iq_queue is None:
                await asyncio.sleep(0.2)
                continue

            if not state.scan_engine.running or state.scan_state.get("state") != "running":
                await asyncio.sleep(0.5)
                continue

            if str(state.scan_state.get("decoder_mode") or "").strip().lower() != "ssb":
                await asyncio.sleep(0.5)
                continue

            try:
                iq = await asyncio.wait_for(_ssb_iq_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            while _ssb_iq_queue is not None and not _ssb_iq_queue.empty():
                try:
                    iq = _ssb_iq_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

            if iq is None or len(iq) == 0:
                continue

            if state.agc_enabled:
                iq, gain_db = apply_agc_smoothed(
                    iq,
                    state.agc_state,
                    target_rms=state.agc_target_rms,
                    max_gain_db=state.agc_max_gain_db,
                    alpha=state.agc_alpha,
                )
                state.last_agc_gain_db = gain_db

            band = state.scan_engine.config.get("band") if state.scan_engine.config else None
            power_db = compute_power_db(iq)
            noise_floor = _update_noise_floor_ssb(band, power_db)
            threshold_dbm = noise_floor + 6.0
            sample_rate = int(state.scan_engine.sample_rate or 0)
            if sample_rate <= 0:
                await asyncio.sleep(0.2)
                continue

            occupancy = estimate_occupancy(
                iq,
                sample_rate,
                threshold_dbm=threshold_dbm,
                adapt=False,
                snr_threshold_db=min(float(state.snr_threshold_db), 3.0),
                min_bw_hz=min(int(state.min_bw_hz), 250),
            )
            if not occupancy:
                continue

            candidates = []
            for candidate in occupancy:
                bw_hz = int(safe_float(candidate.get("bandwidth_hz"), 0) or 0)
                # SSB standard is 2.7 kHz; accept only 2.4–3.0 kHz to reject AM and distorted signals
                if bw_hz < 2400 or bw_hz > 3000:
                    continue
                candidates.append(candidate)
            if not candidates:
                continue

            best = max(candidates, key=lambda item: item.get("snr_db", 0.0))
            offset_hz = best.get("offset_hz")
            center_hz = int(state.scan_engine.center_hz or 0)
            if center_hz <= 0:
                continue
            if offset_hz is not None:
                frequency_hz = int(center_hz + float(offset_hz))
            else:
                frequency_hz = center_hz
            if frequency_hz <= 0:
                continue

            mode_name, mode_confidence = classify_mode_heuristic(
                best.get("bandwidth_hz"),
                best.get("snr_db"),
            )
            freq_hint = hint_mode_by_frequency(
                frequency_hz,
                band_name=band,
                bandwidth_hz=best.get("bandwidth_hz"),
            )
            if freq_hint:
                mode_name = freq_hint

            if mode_name in {"SSB", "AM"}:
                mode_name = "SSB"
                mode_confidence = max(float(mode_confidence or 0.0), 0.6)
            else:
                continue

            min_ssb_confidence = float(getattr(state, "ssb_traffic_min_confidence", 0.78) or 0.78)
            if mode_confidence < min_ssb_confidence:
                continue

            event = {
                "type": "occupancy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "band": band,
                "frequency_hz": frequency_hz,
                "offset_hz": offset_hz,
                "bandwidth_hz": best.get("bandwidth_hz"),
                "power_dbm": power_db,
                "snr_db": best.get("snr_db"),
                "threshold_dbm": best.get("threshold_dbm", threshold_dbm),
                "occupied": bool(best.get("occupied")),
                "mode": mode_name,
                "confidence": float(mode_confidence or 0.0),
                "device": state.scan_state.get("device"),
                "scan_id": state.scan_state.get("scan_id"),
            }

            if not is_plausible_occupancy_event(event):
                continue

            # Feed scan engine candidate-focus logic so SSB scan can hold longer
            # on repeatedly active frequencies without slowing full-band sweep.
            try:
                state.scan_engine.report_ssb_candidate(
                    frequency_hz=frequency_hz,
                    snr_db=float(best.get("snr_db") or 0.0),
                    confidence=float(mode_confidence or 0.0),
                )
            except Exception:
                pass

            state.db.insert_occupancy(event)
            _emit_ssb_traffic_event_from_occupancy(event)

        except asyncio.CancelledError:
            break
        except Exception as exc:
            log(f"ssb_detector_loop_error:{exc}")
            await asyncio.sleep(0.5)


async def _start_ssb_detector(force: bool = False) -> Dict:
    global _ssb_iq_queue, _ssb_detector_task

    if not force and not state.ssb_internal_enable:
        state.decoder_status["internal_native"]["ssb_internal_status"] = _snapshot_ssb_detector_status()
        return {"started": False, "reason": "ssb_internal_disabled"}

    if state.scan_engine is None:
        state.decoder_status["internal_native"]["ssb_internal_status"] = _snapshot_ssb_detector_status()
        return {"started": False, "reason": "scan_engine_unavailable"}

    if _ssb_iq_queue is None:
        _ssb_iq_queue = asyncio.Queue(maxsize=1024)
        state.scan_engine.register_iq_listener(_ssb_iq_queue)

    if _ssb_detector_task is not None and not _ssb_detector_task.done():
        state.decoder_status["internal_native"]["ssb_internal_status"] = _snapshot_ssb_detector_status()
        return {"started": False, "reason": "ssb_detector_already_running"}

    _ssb_detector_task = asyncio.create_task(_run_ssb_detector_loop())
    state.decoder_status["internal_native"]["ssb_internal_status"] = _snapshot_ssb_detector_status()
    return {"started": True, "reason": None}


async def _stop_ssb_detector() -> Dict:
    global _ssb_iq_queue, _ssb_detector_task

    if _ssb_iq_queue is not None:
        try:
            state.scan_engine.unregister_iq_listener(_ssb_iq_queue)
        except Exception:
            pass
        _ssb_iq_queue = None

    if _ssb_detector_task is None:
        state.decoder_status["internal_native"]["ssb_internal_status"] = _snapshot_ssb_detector_status()
        return {"stopped": False, "reason": "ssb_detector_not_running"}

    _ssb_detector_task.cancel()
    try:
        await _ssb_detector_task
    except asyncio.CancelledError:
        pass
    _ssb_detector_task = None

    state.decoder_status["internal_native"]["ssb_internal_status"] = _snapshot_ssb_detector_status()
    return {"stopped": True, "reason": None}


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
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"_ft_external_scan_park dial_hz={dial_hz} running={state.scan_engine.running} device={state.scan_engine.device is not None}")
    if state.scan_engine.running and state.scan_engine.device:
        state.scan_engine.park(int(dial_hz))
    else:
        logger.warning(f"_ft_external_scan_park_skipped dial_hz={dial_hz} running={state.scan_engine.running} device={state.scan_engine.device is not None}")


def _ft_external_scan_unpark():
    """Resume normal scanning after decode."""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"_ft_external_scan_unpark running={state.scan_engine.running}")
    if state.scan_engine.running:
        state.scan_engine.unpark()
    else:
        logger.warning(f"_ft_external_scan_unpark_skipped running={state.scan_engine.running}")


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
    if freq_hz <= 0:
        freq_hz = int(state.scan_engine.center_hz or state.spectrum_cache.get("center_hz") or 0)

    if freq_hz > 0:
        marker_mode = str(payload.get("mode") or "CW").strip().upper()
        if marker_mode not in ("CW", "CW_CANDIDATE"):
            marker_mode = "CW"
        bucket = int(round(freq_hz / 500)) * 500  # 500 Hz bucket
        state.cw_marker_cache[bucket] = {
            "frequency_hz": freq_hz,
            "offset_hz": int(payload.get("df_hz") or 0),
            "mode": marker_mode,
            "snr_db": float(payload.get("snr_db") or 0.0),
            "crest_db": float(payload.get("crest_db") or 0.0),
            "bandwidth_hz": 200,
            "confidence": float(payload.get("confidence") or 0.0),
            "seen_at": _time.time(),
        }

    event_type = str(payload.get("type") or "").strip().lower()
    if event_type == "occupancy":
        if state.scan_state.get("state") != "running":
            return {"status": "ok", "saved": 0, "errors": []}

        try:
            confidence_value = float(payload.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence_value = 0.0
        confidence_value = max(0.0, min(1.0, confidence_value))

        mode_label = str(payload.get("mode") or "").strip().upper()
        if confidence_value > 0.1:
            mode_label = "CW"
        else:
            mode_label = "CW_CANDIDATE"

        try:
            snr_db = float(payload.get("snr_db") or 0.0)
        except (TypeError, ValueError):
            snr_db = 0.0
        if snr_db < 0:
            snr_db = 0.0

        try:
            bandwidth_hz = int(payload.get("bandwidth_hz") or 200)
        except (TypeError, ValueError):
            bandwidth_hz = 200

        occupancy_event = {
            "timestamp": payload.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            "band": payload.get("band") or state.scan_state.get("band"),
            "frequency_hz": freq_hz,
            "bandwidth_hz": max(50, bandwidth_hz),
            "power_dbm": payload.get("power_dbm"),
            "snr_db": snr_db,
            "crest_db": payload.get("crest_db"),
            "threshold_dbm": payload.get("threshold_dbm"),
            "occupied": bool(payload.get("occupied", True)),
            "mode": mode_label,
            "confidence": confidence_value,
            "device": payload.get("device") or state.scan_state.get("device"),
            "scan_id": payload.get("scan_id") or state.scan_state.get("scan_id"),
        }

        if not is_plausible_occupancy_event(occupancy_event):
            return {"status": "ok", "saved": 0, "errors": [{"error": "invalid_occupancy"}]}

        state.db.insert_occupancy(occupancy_event)
        return {"status": "ok", "saved": 1, "errors": []}

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


def _cw_iq_provider_noargs() -> Optional[np.ndarray]:
    """Adapter for CWSweepDecoder: no-argument wrapper around _cw_iq_provider."""
    return _cw_iq_provider(4096)


def _cw_flush_iq() -> None:
    """Drain all pending samples from the CW IQ queue.

    Called by CWSweepDecoder after each park() to discard stale IQ captured
    at the previous SDR centre frequency.
    """
    if _cw_iq_queue is None:
        return
    while True:
        try:
            _cw_iq_queue.get_nowait()
        except asyncio.QueueEmpty:
            break


async def _start_cw_decoder(
    force: bool = False,
    band_start_hz: int = 0,
    band_end_hz: int = 0,
) -> Dict:
    """
    Start CW decoder.

    Args:
        force: Force start even if disabled in config
        band_start_hz: Band start frequency (Hz). If 0, reads from scan engine.
        band_end_hz:   Band end frequency (Hz).   If 0, reads from scan engine.

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
        # Prefer the explicitly-provided band bounds (passed by scan.py before
        # the engine is configured).  Fall back to engine attrs if not given.
        engine = state.scan_engine
        b_start = band_start_hz or getattr(engine, "start_hz", 0)
        b_end   = band_end_hz   or getattr(engine, "end_hz",   0)
        sweep_available = (
            b_start > 0
            and b_end > b_start
            and (b_end - b_start) > state.cw_sweep_step_hz
        )

        if sweep_available:
            from app.decoders.cw_sweep import CWSweepDecoder

            state.cw_decoder = CWSweepDecoder(
                band_start_hz=b_start,
                band_end_hz=b_end,
                step_hz=state.cw_sweep_step_hz,
                dwell_s=state.cw_sweep_dwell_s,
                settle_ms=state.cw_sweep_settle_ms,
                iq_provider=_cw_iq_provider_noargs,
                iq_flush=_cw_flush_iq,
                sample_rate_provider=_cw_sample_rate_provider,
                frequency_provider=_cw_frequency_provider,
                scan_park=lambda hz: state.scan_engine.park(hz),
                scan_unpark=lambda: state.scan_engine.unpark(),
                on_event=_handle_cw_event,
                logger=log,
                target_sample_rate=state.cw_target_sample_rate,
                min_confidence=state.cw_min_confidence,
            )
        else:
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
    rtl_runtime = state.controller.get_rtl_runtime_status(
        center_hz=int(state.scan_engine.center_hz or state.spectrum_cache.get("center_hz") or 0)
    )
    state.decoder_status["internal_native"]["rtl_generation_detected"] = rtl_runtime.get("rtl_generation_detected")
    state.decoder_status["internal_native"]["direct_sampling_policy"] = rtl_runtime.get("direct_sampling_policy")
    state.decoder_status["internal_native"]["direct_sampling_mode_target"] = rtl_runtime.get("direct_sampling_mode_target")
    state.decoder_status["internal_native"]["direct_sampling_mode_applied"] = rtl_runtime.get("direct_sampling_mode_applied")
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
        raw_text = str(text).strip()
        parsed = parse_ssb_asr_text(text)
        if parsed:
            confidence = _score_ssb_confirmed_event(parsed)
            ssb_state = "SSB_CONFIRMED" if confidence >= 0.70 else "SSB_TRAFFIC"
            parsed["confidence"] = confidence
            parsed["ssb_score"] = confidence
            parsed["ssb_state"] = ssb_state
            parsed["ssb_parse_method"] = parsed.get("parse_method") or "unknown"
            parsed["msg"] = raw_text
            events.append(parsed)
        else:
            confidence = _score_ssb_traffic_text(raw_text)
            events.append({
                "raw": raw_text,
                "msg": raw_text,
                "mode": "SSB",
                "confidence": confidence,
                "ssb_score": confidence,
                "ssb_state": "SSB_TRAFFIC",
                "ssb_parse_method": "none",
            })
    
    return _ingest_callsign_payloads(events, payload)


@router.get("/ssb/metrics")
def decoder_ssb_metrics(
    window_minutes: int = Query(15, ge=1, le=1440),
    _: bool = Depends(optional_verify_basic_auth),
) -> Dict:
    """Get SSB confidence/state metrics for a recent time window."""
    metrics = state.db.get_ssb_metrics(window_minutes=window_minutes)
    return {
        "status": "ok",
        "metrics": metrics,
    }


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

