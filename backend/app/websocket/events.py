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
import time as _time_mod
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.dependencies import state
from app.decoders.ingest import build_callsign_event
from app.decoders.parsers import parse_ssb_asr_text
from app.decoders.ssb_asr import get_last_transcript_ssb
from app.dependencies.helpers import (
    safe_float,
    log,
    hint_mode_by_frequency,
    is_plausible_occupancy_event,
    frequency_within_scan_band,
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


def broadcast_event(event: dict) -> None:
    """Public API — broadcast a decoded event to all WS /ws/events clients.

    Thread-safe: uses ``call_soon_threadsafe`` when called from a worker
    thread (e.g. the jt9 decode thread in ft_external).
    """
    msg = {"event": event}
    try:
        loop = asyncio.get_running_loop()
        # We are inside the event-loop — safe to call directly.
        _broadcast(msg)
    except RuntimeError:
        # Called from a non-asyncio thread (ft_external decode thread).
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(_broadcast, msg)
            else:
                _broadcast(msg)
        except RuntimeError:
            _broadcast(msg)


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

    # BW gate: reject phantom events with bandwidth outside SSB voice range.
    # Real SSB voice occupies ~2400-3000 Hz; allow up to 3200 Hz for margin.
    _bw_hz = safe_float(occupancy_event.get("bandwidth_hz"), 0.0) or 0.0
    if _bw_hz > 0 and (_bw_hz < 1200 or _bw_hz > 3200):
        return None

    snr_db = float(safe_float(occupancy_event.get("snr_db"), 0.0) or 0.0)

    # Refresh waterfall marker cache on every valid call (independent of DB
    # debounce) so SSB_VOICE markers stay visible between event emissions.
    if snr_db >= 8.0:
        try:
            _bucket = str(round(frequency_hz / 1000) * 1000)
            base_conf = float(safe_float(occupancy_event.get("confidence"), 0.35) or 0.35)
            _snr_bonus = min(0.25, max(0.0, snr_db / 40.0))
            _mode_bonus = 0.12 if mode_name == "SSB" else 0.04
            _score = min(0.78, max(0.35, base_conf + _snr_bonus + _mode_bonus))
            state.voice_marker_cache[_bucket] = {
                "frequency_hz": float(frequency_hz),
                "offset_hz": 0.0,
                "mode": "SSB_VOICE",
                "snr_db": float(snr_db),
                "bandwidth_hz": float(safe_float(occupancy_event.get("bandwidth_hz"), 2800.0) or 2800.0),
                "confidence": round(_score, 3),
                "seen_at": _time_mod.time(),
            }
        except Exception:
            pass

    now_ts = datetime.now(timezone.utc).timestamp()
    bucket_key = (
        str(occupancy_event.get("band") or ""),
        int(frequency_hz / 2000),
    )
    last_emit_ts = _ssb_traffic_last_emit.get(bucket_key, 0.0)
    if (now_ts - last_emit_ts) < 60.0:
        return None
    _ssb_traffic_last_emit[bucket_key] = now_ts

    if len(_ssb_traffic_last_emit) > 4096:
        stale_before = now_ts - 120.0
        for key, value in list(_ssb_traffic_last_emit.items()):
            if value < stale_before:
                _ssb_traffic_last_emit.pop(key, None)

    base_confidence = float(safe_float(occupancy_event.get("confidence"), 0.35) or 0.35)
    snr_db = float(safe_float(occupancy_event.get("snr_db"), 0.0) or 0.0)
    if snr_db < 8.0:
        return None
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
    resolved_callsign = ""
    parse_method = "occupancy"
    if asr_text:
        raw_field = asr_text
        parsed = parse_ssb_asr_text(asr_text)
        if parsed and parsed.get("callsign"):
            resolved_callsign = parsed["callsign"]
            parse_method = parsed.get("parse_method", "asr")
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
        "callsign": resolved_callsign,
        "raw": raw_field,
        "msg": msg,
        "band": occupancy_event.get("band"),
        "frequency_hz": frequency_hz,
        "snr_db": occupancy_event.get("snr_db"),
        "power_dbm": occupancy_event.get("power_dbm"),
        "confidence": round(ssb_score, 3),
        "ssb_state": "SSB",
        "ssb_score": round(ssb_score, 3),
        "ssb_parse_method": parse_method,
        "source": "internal_ssb_asr" if resolved_callsign else "internal_ssb_occupancy",
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


def update_noise_floor(band: Optional[str], power_db: float) -> float:
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


def update_threshold(band: Optional[str], threshold_dbm: float) -> float:
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
    _diag_counter = 0
    _diag_iq_none = 0
    _diag_no_occ = 0
    _diag_no_freq = 0
    _diag_implausible = 0
    _diag_mode_disabled = 0
    _diag_not_occupied = 0
    _diag_not_running = 0
    _diag_saved = 0
    _diag_occ_throttled = 0

    # Per-frequency-bucket rate limiter for occupancy events.
    # Key: frequency bucket (freq_hz // 5000), Value: last emit timestamp.
    _occ_last_emit: dict[int, float] = {}
    _OCC_MIN_INTERVAL_S = 10.0  # max one occupancy event per 5 kHz bucket per 10 s
    while True:
        try:
            _diag_counter += 1
            # Periodically log diagnostic summary (every ~1000 iterations ≈ 250s)
            if _diag_counter % 1000 == 0:
                log(f"events_loop_diag: iter={_diag_counter} iq_none={_diag_iq_none} no_occ={_diag_no_occ} no_freq={_diag_no_freq} implausible={_diag_implausible} mode_disabled={_diag_mode_disabled} not_occupied={_diag_not_occupied} not_running={_diag_not_running} occ_throttled={_diag_occ_throttled} saved={_diag_saved}")
            # Wait for scan to be running
            if not state.scan_engine.running or state.scan_state.get("state") != "running":
                _diag_not_running += 1
                await asyncio.sleep(0.5)
                continue

            # Read IQ samples
            iq = state.scan_engine.read_iq(2048)
            if iq is None:
                _diag_iq_none += 1
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
                _diag_no_occ += 1
                await asyncio.sleep(0.5)
                continue

            # Pre-filter: keep only segments whose absolute frequency falls
            # within the scan band and whose bandwidth is plausible for HF
            # voice/data modes.  With sample_rate 2.048 MHz the FFT covers
            # ±1 MHz around center_hz — the segmenter will merge wide RFI or
            # roll-off artefacts into mega-segments that must be discarded.
            _center = state.scan_engine.center_hz or 0
            _valid = []
            for seg in occupancy:
                bw = int(seg.get("bandwidth_hz") or 0)
                if bw > 5000 or bw < min_bw_hz:
                    continue
                _off = seg.get("offset_hz")
                _freq = int(_center + float(_off)) if _off is not None else _center
                if not frequency_within_scan_band(_freq, bandwidth_hz=bw):
                    continue
                seg["_abs_freq"] = _freq
                _valid.append(seg)
            if not _valid:
                _diag_implausible += 1
                await asyncio.sleep(0.25)
                continue

            # Select strongest valid signal
            best = max(_valid, key=lambda item: item.get("snr_db", 0.0))

            # Update noise floor from segment detection
            nf_db = best.get("noise_floor_db")
            if nf_db is not None:
                update_noise_floor(band, nf_db)

            # Calculate absolute frequency (pre-computed during filtering)
            offset_hz = best.get("offset_hz")
            frequency_hz = best.get("_abs_freq") or state.scan_engine.center_hz
            if offset_hz is not None and not best.get("_abs_freq"):
                frequency_hz = int(state.scan_engine.center_hz + offset_hz)

            if not frequency_hz or frequency_hz <= 0:
                _diag_no_freq += 1
                await asyncio.sleep(0.5)
                continue

            # Update adaptive threshold
            adaptive_threshold = update_threshold(band, best.get("threshold_dbm"))

            # Classify mode using heuristics
            mode_name, mode_confidence = classify_mode_heuristic(
                best.get("bandwidth_hz"),
                best.get("snr_db"),
                frequency_hz=frequency_hz,
            )

            # Refine with frequency-specific mode hint (FT8/FT4/WSPR windows)
            freq_hint = hint_mode_by_frequency(
                frequency_hz,
                band_name=band,
                bandwidth_hz=best.get("bandwidth_hz")
            )
            if freq_hint:
                mode_name = freq_hint

            # When a non-SSB decoder mode is explicitly active (rotation
            # or manual), force occupancy events to use the active decoder
            # mode.  The bandwidth heuristic often mis-classifies signals
            # (e.g. labels wideband noise as "SSB" on a band scanning FT8),
            # creating phantom modes in analytics charts.
            if selected_decoder_mode in ("ft8", "ft4", "wspr"):
                mode_name = selected_decoder_mode.upper()
            elif selected_decoder_mode == "cw":
                mode_name = "CW"

            # In explicit SSB scan mode, treat voice-like occupancy classes as SSB_TRAFFIC
            # (raw occupancy candidates, not yet confirmed).
            if selected_decoder_mode == "ssb" and mode_name in {"SSB", "AM"}:
                mode_name = "SSB_TRAFFIC"
                mode_confidence = max(float(mode_confidence or 0.0), 0.6)

            # In SSB mode, discard non-SSB events (FSK/PSK, CW, FM, Unknown)
            # — they are artefacts of narrow FFT bins, not useful SSB data.
            if selected_decoder_mode == "ssb" and mode_name != "SSB_TRAFFIC":
                await asyncio.sleep(0.1)
                continue

            # Feed scan engine SSB candidate-focus logic BEFORE the SNR
            # gate so the hold mechanism sees every occupied detection
            # regardless of SNR.  Without this the focus never validates
            # frequencies and no callsign events are emitted.
            if selected_decoder_mode == "ssb":
                _cand_snr = float(best.get("snr_db") or 0.0)
                _cand_conf = float(mode_confidence or 0.0)
                if best.get("occupied") and frequency_hz > 0:
                    try:
                        state.scan_engine.report_ssb_candidate(
                            frequency_hz=frequency_hz,
                            snr_db=_cand_snr,
                            confidence=_cand_conf,
                        )
                    except Exception:
                        pass

            # Minimum SNR gate — suppress marginal detections that flood
            # the events card.  6 dB is one S-unit above noise and the
            # practical readability floor on HF SSB.
            _event_snr = float(best.get("snr_db") or 0.0)
            _MIN_EVENT_SNR_DB = 6.0
            if selected_decoder_mode == "ssb" and _event_snr < _MIN_EVENT_SNR_DB:
                await asyncio.sleep(0.1)
                continue

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
                _diag_implausible += 1
                await asyncio.sleep(0.2)
                continue

            # Check if mode is enabled in settings
            settings = state.db.get_settings()
            modes = settings.get("modes") or {}
            mode_key = str(event.get("mode", "")).lower()

            if modes and mode_key in modes and not modes.get(mode_key, True):
                # Mode disabled by user
                _diag_mode_disabled += 1
                await asyncio.sleep(1.0)
                continue

            # Only process occupied signals
            if not event.get("occupied"):
                _diag_not_occupied += 1
                await asyncio.sleep(0.5)
                continue

            # Only save events during active scan (not in preview or stopped mode)
            if state.scan_state.get("state") != "running":
                _diag_not_running += 1
                await asyncio.sleep(0.5)
                continue

            # In SSB mode, suppress raw occupancy events entirely — only the
            # confirmed callsign events (from 15 s hold validation) are saved
            # and broadcast.  The scan engine still gets report_ssb_candidate()
            # above so the hold mechanism works normally.
            if selected_decoder_mode == "ssb" and mode_name == "SSB_TRAFFIC":
                # Still emit callsign event if frequency is validated
                callsign_event = None
                if state.scan_engine.is_ssb_frequency_validated(frequency_hz):
                    _ws_asr_bucket = int(frequency_hz / 2000)
                    _ws_asr_text = get_last_transcript_ssb(_ws_asr_bucket)
                    callsign_event = _emit_ssb_traffic_event_from_occupancy(event, asr_text=_ws_asr_text)
                if callsign_event:
                    _diag_saved += 1
                    _broadcast({"event": callsign_event})
                await asyncio.sleep(0.25)
                continue

            # ── Per-frequency rate limiter for occupancy events ────────────
            # Prevents DB/UI flood from broadband noise detections.
            # Callsign events from decoders are NOT throttled — only raw
            # occupancy.  Digital-mode windows (FT8/FT4/WSPR) use a shorter
            # cooldown so real activity is not hidden.
            _occ_bucket = int(frequency_hz) // 5000
            _now_mono = _time_mod.monotonic()
            _is_digital = mode_name in {"FT8", "FT4", "WSPR"}
            _cooldown = 3.0 if _is_digital else _OCC_MIN_INTERVAL_S
            _last = _occ_last_emit.get(_occ_bucket, 0.0)
            if (_now_mono - _last) < _cooldown:
                _diag_occ_throttled += 1
                await asyncio.sleep(0.15)
                continue
            _occ_last_emit[_occ_bucket] = _now_mono
            # Prune stale buckets every 500 iterations to avoid memory leak
            if _diag_counter % 500 == 0:
                _cutoff = _now_mono - 60.0
                _occ_last_emit = {k: v for k, v in _occ_last_emit.items() if v > _cutoff}

            # Persist to database
            _diag_saved += 1
            state.db.insert_occupancy(event)

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

            # Rate limit — keep pace with scan dwell (250ms typical)
            await asyncio.sleep(0.25)
        except Exception as _exc:
            log(f"events_loop_crash: {type(_exc).__name__}: {_exc}")
            await asyncio.sleep(1.0)
