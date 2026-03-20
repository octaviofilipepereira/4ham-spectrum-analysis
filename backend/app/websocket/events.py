"""
WebSocket handler for real-time occupancy event detection and streaming.

Provides /ws/events endpoint that performs continuous spectrum monitoring,
signal detection, mode classification, and event persistence.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.dependencies import state
from app.decoders.ingest import build_callsign_event
from app.dependencies.helpers import (
    safe_float,
    log,
    hint_mode_by_frequency,
    is_plausible_occupancy_event,
    touch_decoder_source,
    record_decoder_event_saved,
)
from app.dsp.pipeline import (
    apply_agc_smoothed,
    compute_power_db,
    estimate_occupancy,
    classify_mode_heuristic
)

router = APIRouter()


_ssb_traffic_last_emit = {}


def _emit_ssb_traffic_event_from_occupancy(occupancy_event: dict) -> Optional[dict]:
    """Emit SSB callsign events from occupancy detections in SSB mode.
    
    Returns the created callsign_event (for streaming to client) or None."""
    if not isinstance(occupancy_event, dict):
        return None

    decoder_mode = str(state.scan_state.get("decoder_mode") or "").strip().lower()
    if decoder_mode != "ssb":
        return None

    if not occupancy_event.get("occupied"):
        return None

    mode_name = str(occupancy_event.get("mode") or "").strip().upper()
    if mode_name not in {"SSB", "AM"}:
        return None

    frequency_hz = int(safe_float(occupancy_event.get("frequency_hz"), 0.0) or 0)
    if frequency_hz <= 0:
        return None

    now_ts = datetime.now(timezone.utc).timestamp()
    bucket_key = (
        str(occupancy_event.get("band") or ""),
        int(frequency_hz / 2000),
    )
    last_emit_ts = _ssb_traffic_last_emit.get(bucket_key, 0.0)
    if (now_ts - last_emit_ts) < 8.0:
        return None
    _ssb_traffic_last_emit[bucket_key] = now_ts

    if len(_ssb_traffic_last_emit) > 4096:
        stale_before = now_ts - 120.0
        for key, value in list(_ssb_traffic_last_emit.items()):
            if value < stale_before:
                _ssb_traffic_last_emit.pop(key, None)

    base_confidence = float(safe_float(occupancy_event.get("confidence"), 0.35) or 0.35)
    snr_db = float(safe_float(occupancy_event.get("snr_db"), 0.0) or 0.0)
    snr_bonus = min(0.25, max(0.0, snr_db / 40.0))
    if mode_name == "SSB":
        mode_bonus = 0.12
    else:
        mode_bonus = 0.04
    ssb_score = min(0.78, max(0.35, base_confidence + snr_bonus + mode_bonus))

    msg = f"SSB traffic confirmed @ {frequency_hz / 1_000_000:.3f} MHz"
    payload = {
        "mode": "SSB",
        "callsign": "",
        "raw": msg,
        "msg": msg,
        "band": occupancy_event.get("band"),
        "frequency_hz": frequency_hz,
        "snr_db": occupancy_event.get("snr_db"),
        "power_dbm": occupancy_event.get("power_dbm"),
        "confidence": round(ssb_score, 3),
        "ssb_state": "SSB",
        "ssb_score": round(ssb_score, 3),
        "ssb_parse_method": "occupancy",
        "source": "internal_ssb_occupancy",
        "device": occupancy_event.get("device"),
        "scan_id": occupancy_event.get("scan_id"),
    }
    event = build_callsign_event(payload, state.scan_state)
    if not event:
        return None

    state.db.insert_callsign(event)
    touch_decoder_source(event.get("source"))
    record_decoder_event_saved(event)
    return event


def update_noise_floor(band: str, power_db: float) -> float:
    """
    Update exponential moving average of noise floor for a band.
    
    Args:
        band: Band name (e.g., "20m", "40m")
        power_db: Current power measurement in dB
        
    Returns:
        Updated noise floor in dB
    """
    alpha = 0.1  # Smoothing factor
    current = state.noise_floor.get(band)
    
    if current is None:
        state.noise_floor[band] = power_db
        return power_db
    
    # Exponential moving average
    updated = alpha * power_db + (1 - alpha) * current
    state.noise_floor[band] = updated
    return updated


def update_threshold(band: str, threshold_dbm: float) -> float:
    """
    Update adaptive threshold for a band.
    
    Args:
        band: Band name
        threshold_dbm: New threshold value in dBm
        
    Returns:
        Updated threshold in dBm
    """
    state.threshold_state[band] = threshold_dbm
    return threshold_dbm


@router.websocket("/ws/events")
async def ws_events(websocket: WebSocket) -> None:
    """
    Stream real-time occupancy detection events.
    
    Performs continuous signal processing on IQ samples from the scan engine:
    1. AGC (Automatic Gain Control) if enabled
    2. Power and noise floor estimation
    3. Occupancy detection with SNR calculation
    4. Mode classification (FT8, FT4, APRS, CW, SSB, etc.)
    5. Event validation and filtering
    6. Database persistence
    7. Real-time streaming to client
    
    Args:
        websocket: FastAPI WebSocket connection instance
        
    Message Format:
        {
            "event": {
                "type": "occupancy",
                "timestamp": "2026-02-23T12:34:56.789Z",
                "band": "20m",
                "frequency_hz": 14074000,
                "offset_hz": 0.0,
                "bandwidth_hz": 2500,
                "power_dbm": -75.5,
                "snr_db": 12.3,
                "threshold_dbm": -81.8,
                "occupied": true,
                "mode": "FT8",
                "confidence": 0.95,
                "device": "rtlsdr://0",
                "scan_id": "abc123"
            }
        }
        
    Authentication:
        - If auth is enabled, verifies 'Authorization' header with Basic Auth
        - Closes connection with code 1008 if authentication fails
        
    Mode Filtering:
        - Respects user settings for enabled/disabled modes
        - Skips events if mode is disabled in database settings
        
    Processing Pipeline:
        - Requires scan engine to be running
        - Processes 2048 IQ samples per iteration
        - Applies AGC if enabled
        - Estimates occupancy with adaptive thresholds
        - Filters implausible events
        - Only streams occupied signals
    """
    # Authenticate before accepting connection
    if state.auth_required and not state.verify_auth_transport(
        websocket.headers.get("authorization"),
        websocket.headers.get("cookie"),
    ):
        await websocket.close(code=1008)
        return
    
    await websocket.accept()
    
    while True:
        # Wait for scan to be running
        if not state.scan_engine.running or state.scan_state.get("state") != "running":
            await asyncio.sleep(0.5)
            continue
        
        # Read IQ samples
        iq = state.scan_engine.read_iq(2048)
        if iq is None:
            await asyncio.sleep(0.2)
            continue
        
        # Apply AGC if enabled
        if state.agc_enabled:
            iq, gain_db = apply_agc_smoothed(
                iq,
                state.agc_state,
                target_rms=state.agc_target_rms,
                max_gain_db=state.agc_max_gain_db,
                alpha=state.agc_alpha
            )
            state.last_agc_gain_db = gain_db
        
        # Get current band
        band = state.scan_engine.config.get("band") if state.scan_engine.config else None
        
        # Compute power and update noise floor
        power_db = compute_power_db(iq)
        noise_floor = update_noise_floor(band, power_db)
        threshold_dbm = noise_floor + 6.0  # 6 dB above noise floor
        
        # Detect occupancy
        selected_decoder_mode = str(state.scan_state.get("decoder_mode") or "").strip().lower()
        if selected_decoder_mode == "ssb":
            snr_threshold_db = min(float(state.snr_threshold_db), 3.0)
            min_bw_hz = min(int(state.min_bw_hz), 250)
        else:
            snr_threshold_db = state.snr_threshold_db
            min_bw_hz = state.min_bw_hz

        occupancy = estimate_occupancy(
            iq,
            state.scan_engine.sample_rate,
            threshold_dbm=threshold_dbm,
            adapt=False,
            snr_threshold_db=snr_threshold_db,
            min_bw_hz=min_bw_hz
        )
        
        if not occupancy:
            await asyncio.sleep(0.5)
            continue
        
        # Select strongest signal
        best = max(occupancy, key=lambda item: item.get("snr_db", 0.0))
        
        # Update noise floor from segment detection
        nf_db = best.get("noise_floor_db")
        if nf_db is not None:
            update_noise_floor(band, nf_db)
        
        # Calculate absolute frequency
        offset_hz = best.get("offset_hz")
        frequency_hz = state.scan_engine.center_hz
        if offset_hz is not None:
            frequency_hz = int(state.scan_engine.center_hz + offset_hz)
        
        if not frequency_hz or frequency_hz <= 0:
            await asyncio.sleep(0.5)
            continue
        
        # Update adaptive threshold
        adaptive_threshold = update_threshold(band, best.get("threshold_dbm"))
        
        # Classify mode using heuristics
        mode_name, mode_confidence = classify_mode_heuristic(
            best.get("bandwidth_hz"),
            best.get("snr_db")
        )
        
        # Refine with frequency-specific mode hint (FT8/FT4/WSPR windows)
        freq_hint = hint_mode_by_frequency(
            frequency_hz,
            band_name=band,
            bandwidth_hz=best.get("bandwidth_hz")
        )
        if freq_hint:
            mode_name = freq_hint

        # In explicit SSB scan mode, treat voice-like occupancy classes as SSB_TRAFFIC
        # (raw occupancy candidates, not yet confirmed).
        if selected_decoder_mode == "ssb" and mode_name in {"SSB", "AM"}:
            mode_name = "SSB_TRAFFIC"
            mode_confidence = max(float(mode_confidence or 0.0), 0.6)
        
        # Build event
        event = {
            "type": "occupancy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "band": band,
            "frequency_hz": frequency_hz,
            "offset_hz": offset_hz,
            "bandwidth_hz": best["bandwidth_hz"],
            "power_dbm": power_db,
            "snr_db": best.get("snr_db"),
            "threshold_dbm": adaptive_threshold or best.get("threshold_dbm", threshold_dbm),
            "occupied": best["occupied"],
            "mode": mode_name,
            "confidence": mode_confidence,
            "device": state.scan_state.get("device"),
            "scan_id": state.scan_state.get("scan_id")
        }
        
        # Validate plausibility
        if not is_plausible_occupancy_event(event):
            await asyncio.sleep(0.2)
            continue
        
        # Check if mode is enabled in settings
        settings = state.db.get_settings()
        modes = settings.get("modes") or {}
        mode_key = str(event.get("mode", "")).lower()
        
        if modes and mode_key in modes and not modes.get(mode_key, True):
            # Mode disabled by user
            await asyncio.sleep(1.0)
            continue
        
        # Only stream occupied signals
        if not event.get("occupied"):
            await asyncio.sleep(0.5)
            continue
        
        # Only save events during active scan (not in preview or stopped mode)
        if state.scan_state.get("state") != "running":
            await asyncio.sleep(0.5)
            continue
        
        # Persist to database
        state.db.insert_occupancy(event)
        
        # Emit confirmed callsign event (if threshold met) and also stream it to client
        callsign_event = _emit_ssb_traffic_event_from_occupancy(event)
        
        # Stream both events to client: raw occupancy + confirmed callsign
        await websocket.send_json({"event": event})
        if callsign_event:
            await websocket.send_json({"event": callsign_event})
        
        # Rate limit
        await asyncio.sleep(1.0)
