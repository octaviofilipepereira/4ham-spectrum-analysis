"""
WebSocket handler for real-time occupancy event detection and streaming.

Provides /ws/events endpoint that performs continuous spectrum monitoring,
signal detection, mode classification, and event persistence.

Architecture:
- _run_occupancy_detection_loop() is a singleton background task started at
  app startup (main.py).  It processes IQ samples, persists events to the DB,
  and fan-outs serialised JSON messages to all connected WS clients via a set
  of per-client asyncio.Queue instances.
- ws_events() simply subscribes a queue, relays messages to the browser, and
  unsubscribes when the browser disconnects.  Occupancy detection therefore
  continues uninterrupted even when no browser is connected.
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.dependencies import state
from app.decoders.ingest import build_callsign_event
from app.decoders.ssb_asr import get_last_transcript_ssb, maybe_transcribe_ssb
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

# ---------------------------------------------------------------------------
# Broadcast bus – one asyncio.Queue per connected WS client
# ---------------------------------------------------------------------------
_event_subscribers: List[asyncio.Queue] = []


def _subscribe_events() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _event_subscribers.append(q)
    return q


def _unsubscribe_events(q: asyncio.Queue) -> None:
    try:
        _event_subscribers.remove(q)
    except ValueError:
        pass


def _broadcast(msg: dict) -> None:
    """Put msg into every subscriber queue, dropping if a queue is full."""
    for q in _event_subscribers:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass


def _emit_ssb_traffic_event_from_occupancy(occupancy_event: dict, asr_text: str = "") -> Optional[dict]:
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
    if mode_name not in {"SSB", "SSB_TRAFFIC", "AM"}:
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

    freq_khz = frequency_hz / 1000.0
    snr_str = f"+{snr_db:.1f}" if snr_db >= 0 else f"{snr_db:.1f}"
    conf_pct = int(round(ssb_score * 100))
    band_str = str(occupancy_event.get("band") or "")
    msg = f"SSB voice confirmed {freq_khz:.1f} kHz"
    if band_str:
        msg += f" ({band_str})"
    msg += f" | SNR {snr_str} dB | Conf {conf_pct}%"

    bw_hz = occupancy_event.get("bandwidth_hz")
    power_dbm_val = occupancy_event.get("power_dbm")
    if asr_text:
        raw_field = asr_text
    else:
        proof_parts = []
        if bw_hz is not None:
            proof_parts.append(f"BW {int(bw_hz)} Hz")
        if power_dbm_val is not None:
            proof_parts.append(f"PWR {float(power_dbm_val):.1f} dBm")
        proof_parts.append("Voice spectral signature")
        raw_field = " · ".join(proof_parts)

    payload = {
        "mode": "SSB",
        "callsign": "",
        "raw": raw_field,
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
    """Subscribe to the occupancy detection broadcast bus and relay to browser.

    Authentication is enforced before accepting the connection.  The actual
    signal-processing work is done by _run_occupancy_detection_loop() which
    runs as a server-level background task independent of this connection.
    """
    if state.auth_required and not state.verify_auth_transport(
        websocket.headers.get("authorization"),
        websocket.headers.get("cookie"),
    ):
        await websocket.close(code=1008)
        return

    await websocket.accept()
    q = _subscribe_events()
    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # Send a keep-alive ping so idle connections are not dropped by
                # reverse-proxies or browsers.
                try:
                    await websocket.send_json({"ping": True})
                except Exception:
                    break
                continue
            try:
                await websocket.send_json(msg)
            except Exception:
                break
    except WebSocketDisconnect:
        pass
    finally:
        _unsubscribe_events(q)


async def _run_occupancy_detection_loop() -> None:
    """Background task: continuous occupancy detection, DB persistence, and fan-out.

    Runs for the lifetime of the server process.  Occupancy detection proceeds
    even when no WebSocket client is connected so that events are never missed
    due to a browser disconnect or reload.
    """
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

        # Only process occupied signals
        if not event.get("occupied"):
            await asyncio.sleep(0.5)
            continue

        # Only save events during active scan (not in preview or stopped mode)
        if state.scan_state.get("state") != "running":
            await asyncio.sleep(0.5)
            continue

        # Persist to database
        state.db.insert_occupancy(event)

        # Feed scan engine SSB candidate-focus logic when in SSB mode
        if selected_decoder_mode == "ssb" and event.get("occupied"):
            try:
                state.scan_engine.report_ssb_candidate(
                    frequency_hz=frequency_hz,
                    snr_db=float(best.get("snr_db") or 0.0),
                    confidence=float(mode_confidence or 0.0),
                )
            except Exception:
                pass
            # Fire background Whisper transcription whenever enough audio is
            # buffered, independent of the validation hold mechanism.
            maybe_transcribe_ssb(int(frequency_hz / 2000))

        # Emit confirmed callsign event only after 15s hold validation
        callsign_event = None
        if state.scan_engine.is_ssb_frequency_validated(frequency_hz):
            _ws_asr_bucket = int(frequency_hz / 2000)
            _ws_asr_text = get_last_transcript_ssb(_ws_asr_bucket)
            callsign_event = _emit_ssb_traffic_event_from_occupancy(event, asr_text=_ws_asr_text)

        # Fan-out both events to all connected WS clients
        _broadcast({"event": event})
        if callsign_event:
            _broadcast({"event": callsign_event})

        # Rate limit
        await asyncio.sleep(1.0)
