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
import os
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
    maidenhead_to_latlon,
)
from app.decoders.ingest import build_callsign_event
from app.decoders.parsers import parse_aprs_line, parse_cw_text, parse_ssb_asr_text
from app.decoders.direwolf_kiss import (
    kiss_loop,
    get_kiss_config,
    describe_kiss,
    parse_kiss_frame,
)
from app.decoders.aprs_is import (
    aprs_is_loop,
    check_internet,
    parse_aprs_is_line,
)
from app.decoders.lora_aprs import (
    lora_aprs_loop,
    get_lora_config,
    describe_lora,
)
from app.decoders.launchers import resolve_command, start_process, stop_process
from app.decoders.ssb_asr import (
    feed_iq_ssb,
    is_ssb_asr_available,
    get_last_transcript_ssb,
    maybe_transcribe_ssb,
)
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


def _emit_ssb_traffic_event_from_occupancy(occupancy_event: Dict, asr_text: str = "") -> None:
    if not isinstance(occupancy_event, dict):
        return

    if not occupancy_event.get("occupied"):
        return

    mode_name = str(occupancy_event.get("mode") or "").strip().upper()
    if mode_name not in ("SSB", "SSB_TRAFFIC"):
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
    if (now_ts - last_emit_ts) < 30.0:
        return
    _ssb_traffic_last_emit[bucket_key] = now_ts

    if len(_ssb_traffic_last_emit) > 4096:
        stale_before = now_ts - 120.0
        for key, value in list(_ssb_traffic_last_emit.items()):
            if value < stale_before:
                _ssb_traffic_last_emit.pop(key, None)

    base_confidence = float(safe_float(occupancy_event.get("confidence"), 0.35) or 0.35)
    snr_db = float(safe_float(occupancy_event.get("snr_db"), 0.0) or 0.0)

    # Gate: reject weak signals below the global SNR threshold
    _snr_floor = float(getattr(state, "snr_threshold_db", 8.0) or 8.0)
    if snr_db < _snr_floor:
        return

    snr_bonus = min(0.25, max(0.0, snr_db / 40.0))
    ssb_score = min(0.95, max(0.35, base_confidence + snr_bonus))
    if ssb_score < float(getattr(state, "ssb_traffic_min_confidence", 0.55) or 0.55):
        return

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
        return

    state.db.insert_callsign(event)
    touch_decoder_source(event.get("source"))
    record_decoder_event_saved(event)

    # Inject SSB VOICE marker ONLY when ASR text confirms actual voice.
    # Occupancy-only detections (no asr_text) fire too often and flood the
    # waterfall with false VOICE DETECTED markers across the whole band.
    if asr_text:
        try:
            import time as _t
            _freq = float(frequency_hz)
            _bucket = str(round(_freq / 1000) * 1000)
            state.voice_marker_cache[_bucket] = {
                "frequency_hz": _freq,
                "offset_hz": 0.0,
                "mode": "SSB_VOICE",
                "snr_db": float(occupancy_event.get("snr_db") or 0.0),
                "bandwidth_hz": float(occupancy_event.get("bandwidth_hz") or 2800.0),
                "confidence": round(ssb_score, 3),
                "seen_at": _t.time(),
            }
        except Exception:
            pass

    # Broadcast to WS /ws/events clients so the frontend Events panel and
    # waterfall markers update immediately (not only via 5 s HTTP poll).
    try:
        from app.websocket.events import broadcast_event
        broadcast_event(event)
    except Exception:
        pass  # best-effort — DB persistence already succeeded


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

            # Use non-blocking get_nowait + sleep instead of wait_for(queue.get(), timeout)
            # to avoid the Python 3.10 asyncio.wait_for cancellation propagation bug
            # (CPython issue #32751) where task.cancel() can be silently absorbed inside
            # wait_for, preventing _stop_ssb_detector from completing in bounded time.
            try:
                iq = _ssb_iq_queue.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.05)
                continue

            # Collect all queued chunks; keep latest for detection, all for ASR
            _iq_chunks_asr = [iq]
            while _ssb_iq_queue is not None and not _ssb_iq_queue.empty():
                try:
                    iq = _ssb_iq_queue.get_nowait()
                    _iq_chunks_asr.append(iq)
                except asyncio.QueueEmpty:
                    break

            if iq is None or len(iq) == 0:
                continue

            # Yield to the event loop before heavy synchronous DSP work so that
            # incoming HTTP requests (e.g. POST /api/scan/mode) are not starved.
            await asyncio.sleep(0)

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

            center_hz = int(state.scan_engine.center_hz or 0)

            # During an active SSB focus hold, bypass occupancy detection
            # and feed ALL IQ chunks directly to ASR.  The hold already
            # validates the frequency — requiring per-burst SSB detection
            # drops audio whenever FFT noise causes a classification miss.
            if center_hz > 0 and state.scan_engine.is_ssb_frequency_validated(center_hz):
                if is_ssb_asr_available():
                    _hold_bucket = int(center_hz / 2000)
                    for _chunk in _iq_chunks_asr:
                        feed_iq_ssb(_hold_bucket, _chunk, sample_rate,
                                    0.0, center_hz)
                    maybe_transcribe_ssb(_hold_bucket)
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
                # Accept SSB voice bandwidths only: 1200–2800 Hz.
                # Wider signals are broadband noise, not SSB.
                if bw_hz < 1200 or bw_hz > 2800:
                    continue
                candidates.append(candidate)
            if not candidates:
                continue

            best = max(candidates, key=lambda item: item.get("snr_db", 0.0))
            offset_hz = best.get("offset_hz")
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
                frequency_hz=frequency_hz,
            )
            freq_hint = hint_mode_by_frequency(
                frequency_hz,
                band_name=band,
                bandwidth_hz=best.get("bandwidth_hz"),
            )
            if freq_hint:
                mode_name = freq_hint

            if mode_name in {"SSB", "AM"}:
                mode_name = "SSB_TRAFFIC"
                mode_confidence = max(float(mode_confidence or 0.0), 0.6)
            else:
                continue

            # Accumulate audio for ASR for all SSB detections, regardless of
            # confidence threshold — the buffer must be ready when validation fires.
            if is_ssb_asr_available() and frequency_hz > 0:
                _ssb_asr_bucket = int(frequency_hz / 2000)
                for _chunk in _iq_chunks_asr:
                    feed_iq_ssb(_ssb_asr_bucket, _chunk, sample_rate,
                                float(offset_hz or 0.0), frequency_hz)
                # Fire background Whisper transcription whenever buffer is ready.
                # Non-blocking: result cached in get_last_transcript_ssb().
                maybe_transcribe_ssb(_ssb_asr_bucket)

            min_ssb_confidence = float(getattr(state, "ssb_traffic_min_confidence", 0.55) or 0.55)
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

            # Do NOT insert occupancy events here — this loop runs at full
            # dwell rate and would flood the Events card.  The events.py loop
            # handles callsign event emission for validated frequencies.

            # Only emit confirmed callsign/SSB event after 15s hold validation
            if state.scan_engine.is_ssb_frequency_validated(frequency_hz):
                _ssb_asr_bucket = int(frequency_hz / 2000)
                # Non-blocking: use cached transcript produced by background task.
                _asr_text = get_last_transcript_ssb(_ssb_asr_bucket)
                _emit_ssb_traffic_event_from_occupancy(event, asr_text=_asr_text)

        except asyncio.CancelledError:
            break
        except Exception as exc:
            log(f"ssb_detector_loop_error:{exc}")
            await asyncio.sleep(0.5)


# ═══════════════════════════════════════════════════════════════════
# KISS / APRS Loop — Direwolf TCP KISS interface
# ═══════════════════════════════════════════════════════════════════


def _kiss_on_event(event: Dict):
    """Callback invoked by kiss_loop for each decoded APRS frame."""
    if not event or not isinstance(event, dict):
        return
    # Update last-packet timestamp
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    state.decoder_status["direwolf_kiss"]["last_packet_at"] = now_iso
    # Enrich with APRS scan frequency (144.800 MHz for Region 1)
    if not event.get("frequency_hz"):
        scan = state.scan_state.get("scan")
        if scan and scan.get("start_hz"):
            event["frequency_hz"] = int(scan["start_hz"])
        else:
            event["frequency_hz"] = 144_800_000
    # Ingest through the standard pipeline
    result = _ingest_callsign_payloads([event], {})
    # Broadcast to WebSocket so frontend markers and Events panel update
    if result and result.get("saved", 0) > 0:
        try:
            from app.websocket.events import broadcast_event
            broadcast_event(event)
        except Exception:
            pass  # best-effort — DB persistence already succeeded


def _kiss_status_cb(status: str, detail: str):
    """Callback invoked by kiss_loop for connection state changes."""
    kiss_st = state.decoder_status["direwolf_kiss"]
    if status == "connected":
        kiss_st["connected"] = True
        kiss_st["address"] = detail
        kiss_st["last_error"] = None
    elif status == "disconnected":
        kiss_st["connected"] = False
    elif status == "error":
        kiss_st["connected"] = False
        kiss_st["last_error"] = detail


def _sync_direwolf_mycall(cmd: list):
    """Update MYCALL in direwolf.conf with the station callsign from settings."""
    try:
        settings = state.db.get_settings()
        callsign = str((settings.get("station") or {}).get("callsign") or "").strip().upper()
        if not callsign:
            return
        # Find the config file path from -c flag in the command
        conf_path = None
        for i, arg in enumerate(cmd):
            if arg == "-c" and i + 1 < len(cmd):
                conf_path = cmd[i + 1]
                break
        if not conf_path or not os.path.isfile(conf_path):
            return
        text = open(conf_path, "r").read()
        updated = re.sub(r"^MYCALL\s+.*$", f"MYCALL {callsign}", text, flags=re.MULTILINE)
        if updated != text:
            open(conf_path, "w").write(updated)
            log(f"direwolf_mycall_synced:{callsign}")
    except Exception as exc:
        log(f"direwolf_mycall_sync_failed:{exc}")


async def _start_kiss_loop(force: bool = False) -> Dict:
    """Start the KISS TCP loop that connects to Direwolf."""
    config = get_kiss_config()
    if not config:
        if not force:
            return {"started": False, "reason": "kiss_not_configured"}
        return {"started": False, "reason": "kiss_not_configured"}

    if state.kiss_task is not None and not state.kiss_task.done():
        return {"started": False, "reason": "kiss_already_running"}

    # Launch Direwolf / rtl_fm pipeline when needed
    kiss_st = state.decoder_status["direwolf_kiss"]
    should_launch = (force or kiss_st["autostart"]) and state.direwolf_process is None
    if should_launch:
        cmd = resolve_command("DIREWOLF_CMD", "direwolf -t 0 -p")
        if cmd:
            # Sync MYCALL in direwolf.conf with the station callsign from Admin Config
            _sync_direwolf_mycall(cmd)

            # Only launch rtl_fm → Direwolf pipeline when the user explicitly
            # selects APRS mode (force=True).  rtl_fm grabs the RTL-SDR device
            # exclusively, which would block the waterfall/SoapySDR scan.
            # On autostart we only start the KISS TCP listener (no rtl_fm).
            rtl_fm_cmd = resolve_command(
                "RTL_FM_CMD",
                "rtl_fm -f 144800000 -s 22050 -g 42",
            ) if force else None

            if rtl_fm_cmd:
                try:
                    import subprocess
                    log_dir = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)),
                        "..", "..", "logs",
                    )
                    log_dir = os.path.normpath(log_dir)
                    os.makedirs(log_dir, exist_ok=True)
                    dw_log_path = os.path.join(log_dir, "direwolf_pipe.log")
                    dw_log_fp = open(dw_log_path, "w")

                    env = dict(os.environ)
                    env["FOURHAM_MANAGED"] = "1"
                    env["FOURHAM_MANAGED_BY"] = "4ham-spectrum-analysis"

                    # Use subprocess.Popen for real OS-level pipe between
                    # rtl_fm stdout → Direwolf stdin (asyncio subprocess
                    # doesn't support piping between two child processes).
                    rtl_fm_proc = subprocess.Popen(
                        rtl_fm_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        env=env,
                    )
                    state.rtl_fm_process = rtl_fm_proc

                    # Start Direwolf in stdin-pipe mode, reading audio from rtl_fm
                    dw_pipe_cmd = list(cmd) + ["-r", "22050", "-n", "1", "-b", "16", "-"]
                    dw_proc = subprocess.Popen(
                        dw_pipe_cmd,
                        stdin=rtl_fm_proc.stdout,
                        stdout=dw_log_fp,
                        stderr=subprocess.STDOUT,
                        env=env,
                    )
                    state.direwolf_process = dw_proc
                    # Allow rtl_fm to receive SIGPIPE if Direwolf exits
                    rtl_fm_proc.stdout.close()

                    kiss_st["process_running"] = True
                    kiss_st["process_pid"] = state.direwolf_process.pid
                    log(
                        f"rtl_fm_direwolf_pipeline_started:"
                        f"rtl_fm_pid={rtl_fm_proc.pid} "
                        f"direwolf_pid={state.direwolf_process.pid}"
                    )
                    # Give Direwolf time to open the KISS TCP port
                    await asyncio.sleep(2.0)
                except Exception as exc:
                    log(f"rtl_fm_direwolf_pipeline_start_failed:{exc}")
                    kiss_st["last_error"] = str(exc)
                    # Clean up partial start
                    if state.rtl_fm_process is not None:
                        try:
                            state.rtl_fm_process.kill()
                        except Exception:
                            pass
                        state.rtl_fm_process = None
            else:
                # Autostart or rtl_fm not available: Direwolf soundcard mode
                # (does NOT grab the RTL-SDR, safe for concurrent waterfall)
                try:
                    state.direwolf_process = await start_process(cmd)
                    kiss_st["process_running"] = True
                    kiss_st["process_pid"] = state.direwolf_process.pid
                    log(f"direwolf_process_started:pid={state.direwolf_process.pid}")
                    await asyncio.sleep(2.0)
                except Exception as exc:
                    log(f"direwolf_process_start_failed:{exc}")
                    kiss_st["last_error"] = str(exc)

    # Reset the dedicated KISS stop event so the loop starts fresh
    state.kiss_stop.clear()

    state.kiss_task = asyncio.create_task(
        kiss_loop(
            on_event=_kiss_on_event,
            stop_event=state.kiss_stop,
            logger=lambda msg: log(msg),
            reconnect_delay=3.0,
            status_cb=_kiss_status_cb,
        )
    )
    kiss_st["enabled"] = True
    kiss_st["address"] = describe_kiss()
    log(f"kiss_loop_started:{describe_kiss()}")
    return {"started": True, "reason": None}


async def _stop_kiss_loop() -> Dict:
    """Stop the KISS TCP loop."""
    if state.kiss_task is None:
        return {"stopped": False, "reason": "kiss_not_running"}

    # Signal the KISS loop to stop (dedicated event, won't affect other decoders)
    state.kiss_stop.set()

    if not state.kiss_task.done():
        state.kiss_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(state.kiss_task), timeout=3.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    state.kiss_task = None
    state.decoder_status["direwolf_kiss"]["connected"] = False

    # Stop rtl_fm process if it was used (rtl_fm → Direwolf pipeline)
    # These are subprocess.Popen objects (sync), not asyncio subprocesses,
    # so we use asyncio.to_thread for the blocking .wait() call.
    import subprocess as _sp
    for label, attr in [("rtl_fm", "rtl_fm_process"), ("direwolf", "direwolf_process")]:
        proc = getattr(state, attr, None)
        if proc is None:
            continue
        try:
            if isinstance(proc, _sp.Popen):
                proc.terminate()
                try:
                    await asyncio.to_thread(proc.wait, timeout=3)
                except _sp.TimeoutExpired:
                    proc.kill()
                    await asyncio.to_thread(proc.wait, timeout=3)
            else:
                await stop_process(proc)
            log(f"{label}_process_stopped:pid={proc.pid}")
        except Exception as exc:
            log(f"{label}_process_stop_failed:{exc}")
        setattr(state, attr, None)
        state.decoder_status["direwolf_kiss"]["process_running"] = False
        state.decoder_status["direwolf_kiss"]["process_pid"] = None

    log("kiss_loop_stopped")
    return {"stopped": True, "reason": None}


# ── APRS-IS (Internet feed) ─────────────────────────────────────────

def _aprs_is_on_event(event: Dict):
    """Callback invoked by aprs_is_loop for each decoded APRS-IS packet."""
    if not event or not isinstance(event, dict):
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    state.decoder_status["aprs_is"]["last_packet_at"] = now_iso
    # Enrich with APRS frequency
    if not event.get("frequency_hz"):
        event["frequency_hz"] = 144800000
    result = _ingest_callsign_payloads([event], {})
    if result and result.get("saved", 0) > 0:
        try:
            from app.websocket.events import broadcast_event
            broadcast_event(event)
        except Exception:
            pass


def _aprs_is_status_cb(status: str, detail: str):
    """Callback invoked by aprs_is_loop for connection state changes."""
    is_st = state.decoder_status["aprs_is"]
    if status == "connected":
        is_st["connected"] = True
        is_st["address"] = detail
        is_st["last_error"] = None
    elif status == "disconnected":
        is_st["connected"] = False
    elif status in ("error", "connecting"):
        if status == "error":
            is_st["connected"] = False
            is_st["last_error"] = detail


def _get_station_coords() -> tuple:
    """Return (callsign, lat, lon) from settings, or (None, None, None)."""
    try:
        settings = state.db.get_settings()
        station = settings.get("station") or {}
        callsign = str(station.get("callsign") or "").strip().upper()
        locator = str(station.get("locator") or "").strip().upper()
        if not callsign or not locator:
            return None, None, None
        pos = maidenhead_to_latlon(locator)
        if not pos:
            return callsign, None, None
        return callsign, pos[0], pos[1]
    except Exception:
        return None, None, None


async def _start_aprs_is_loop() -> Dict:
    """Start the APRS-IS Internet feed loop."""
    if state.aprs_is_task is not None and not state.aprs_is_task.done():
        return {"started": False, "reason": "aprs_is_already_running"}

    # Check internet connectivity
    has_internet = await asyncio.to_thread(check_internet)
    state.decoder_status["aprs_is"]["internet_available"] = has_internet
    if not has_internet:
        log("aprs_is_no_internet:skipping APRS-IS (no internet connectivity)")
        return {"started": False, "reason": "no_internet"}

    callsign, lat, lon = _get_station_coords()
    if not callsign or lat is None or lon is None:
        log("aprs_is_no_station_config:station callsign/locator not configured")
        return {"started": False, "reason": "no_station_config"}

    state.aprs_is_stop.clear()
    state.aprs_is_task = asyncio.create_task(
        aprs_is_loop(
            callsign=callsign,
            lat=lat,
            lon=lon,
            on_event=_aprs_is_on_event,
            stop_event=state.aprs_is_stop,
            logger=lambda msg: log(msg),
            reconnect_delay=10.0,
            status_cb=_aprs_is_status_cb,
        )
    )
    state.decoder_status["aprs_is"]["enabled"] = True
    log(f"aprs_is_loop_started:callsign={callsign} lat={lat:.4f} lon={lon:.4f}")
    return {"started": True, "reason": None}


async def _stop_aprs_is_loop() -> Dict:
    """Stop the APRS-IS Internet feed loop."""
    if state.aprs_is_task is None:
        return {"stopped": False, "reason": "aprs_is_not_running"}

    state.aprs_is_stop.set()
    if not state.aprs_is_task.done():
        state.aprs_is_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(state.aprs_is_task), timeout=3.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    state.aprs_is_task = None
    state.decoder_status["aprs_is"]["connected"] = False
    state.decoder_status["aprs_is"]["enabled"] = False
    log("aprs_is_loop_stopped")
    return {"stopped": True, "reason": None}


# ── LoRa APRS (gr-lora_sdr → UDP) ──────────────────────────────────

def _lora_aprs_on_event(event: Dict):
    """Callback invoked by lora_aprs_loop for each decoded LoRa-APRS frame."""
    if not event or not isinstance(event, dict):
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    state.decoder_status["lora_aprs"]["last_packet_at"] = now_iso
    # Enrich with LoRa-APRS frequency (868.000 MHz EU SRD band, IARU Region 1).
    if not event.get("frequency_hz"):
        event["frequency_hz"] = 868_000_000
    result = _ingest_callsign_payloads([event], {})
    if result and result.get("saved", 0) > 0:
        try:
            from app.websocket.events import broadcast_event
            broadcast_event(event)
        except Exception:
            pass


def _lora_aprs_status_cb(status: str, detail: str):
    """Callback invoked by lora_aprs_loop for socket state changes."""
    lora_st = state.decoder_status["lora_aprs"]
    if status == "connected":
        lora_st["connected"] = True
        lora_st["address"] = detail
        lora_st["last_error"] = None
    elif status == "disconnected":
        lora_st["connected"] = False
    elif status == "error":
        lora_st["connected"] = False
        lora_st["last_error"] = detail


async def _start_lora_aprs_loop(force: bool = False) -> Dict:
    """Start the LoRa-APRS UDP listener loop."""
    config = get_lora_config()
    if not config:
        return {"started": False, "reason": "lora_aprs_not_configured"}

    if state.lora_aprs_task is not None and not state.lora_aprs_task.done():
        return {"started": False, "reason": "lora_aprs_already_running"}

    state.lora_aprs_stop.clear()
    state.lora_aprs_task = asyncio.create_task(
        lora_aprs_loop(
            on_event=_lora_aprs_on_event,
            stop_event=state.lora_aprs_stop,
            logger=lambda msg: log(msg),
            reconnect_delay=3.0,
            status_cb=_lora_aprs_status_cb,
        )
    )
    state.decoder_status["lora_aprs"]["enabled"] = True
    state.decoder_status["lora_aprs"]["address"] = describe_lora()
    log(f"lora_aprs_loop_started:{describe_lora()}")
    return {"started": True, "reason": None}


async def _stop_lora_aprs_loop() -> Dict:
    """Stop the LoRa-APRS UDP listener loop."""
    if state.lora_aprs_task is None:
        return {"stopped": False, "reason": "lora_aprs_not_running"}

    state.lora_aprs_stop.set()
    if not state.lora_aprs_task.done():
        state.lora_aprs_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(state.lora_aprs_task), timeout=3.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    state.lora_aprs_task = None
    state.decoder_status["lora_aprs"]["connected"] = False
    state.decoder_status["lora_aprs"]["enabled"] = False
    log("lora_aprs_loop_stopped")
    return {"stopped": True, "reason": None}



async def _start_ssb_detector(force: bool = False) -> Dict:
    global _ssb_iq_queue, _ssb_detector_task

    if not force and not state.ssb_internal_enable:
        state.decoder_status["internal_native"]["ssb_internal_status"] = _snapshot_ssb_detector_status()
        return {"started": False, "reason": "ssb_internal_disabled"}

    if state.scan_engine is None:
        state.decoder_status["internal_native"]["ssb_internal_status"] = _snapshot_ssb_detector_status()
        return {"started": False, "reason": "scan_engine_unavailable"}

    if _ssb_iq_queue is None:
        _ssb_iq_queue = asyncio.Queue(maxsize=8192)
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
        # Use shield so the timeout firing does not issue a second cancel on the
        # task.  The task already received cancel() above; shield lets us bound
        # how long we wait without interfering.  Maximum wait: 2 s.
        await asyncio.wait_for(asyncio.shield(_ssb_detector_task), timeout=2.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
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
    background_aprs_sources = {"direwolf", "aprs_is", "lora_aprs"}
    
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

        is_background_aprs = str(event.get("source") or "").strip().lower() in background_aprs_sources
        
        # Background APRS sources (Direwolf / APRS-IS / LoRa APRS) are
        # independent feeders and must be ingested even when the main scan
        # engine is stopped, in preview, or focused on another mode.
        if state.scan_state.get("state") != "running" and not is_background_aprs:
            continue
        
        # Filter events by selected decoder mode (case-insensitive).
        # FT8 and FT4 are treated as the same family — selecting either
        # mode accepts events from both sub-modes.
        _FT_FAMILY = {"FT8", "FT4"}
        event_mode = str(event.get("mode", "")).strip().upper()
        selected_mode = str(state.scan_state.get("decoder_mode", "")).strip().upper()
        if selected_mode and event_mode != selected_mode and not is_background_aprs:
            if not (event_mode in _FT_FAMILY and selected_mode in _FT_FAMILY):
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
    """Handle event from external FT decoder.

    Saves to DB via _ingest_callsign_payloads AND broadcasts the event
    to all connected /ws/events clients so waterfall markers appear
    immediately instead of waiting for the 5 s HTTP polling cycle.
    """
    result = _ingest_callsign_payloads([payload], {"source": "internal_ft_external"})
    # Broadcast to WS clients only when the event was actually saved.
    if result.get("saved", 0) > 0:
        try:
            from app.websocket.events import broadcast_event
            broadcast_event(payload)
        except Exception:
            pass  # best-effort — DB persistence already succeeded
    return result


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
        "sources": ["direwolf", "aprs_is", "cw", "asr", "dsp", "internal_ft", "external_ft", "internal_cw", "internal_ssb", "internal_psk"],
        "status": state.decoder_status
    }


@router.get("/aprs-connectivity")
async def aprs_connectivity(_: bool = Depends(optional_verify_basic_auth)) -> Dict:
    """
    Check APRS connectivity: internet availability and APRS-IS status.
    Used by frontend to show RF-only warning when no internet.
    """
    has_internet = await asyncio.to_thread(check_internet, 3.0)
    state.decoder_status["aprs_is"]["internet_available"] = has_internet
    return {
        "internet": has_internet,
        "aprs_is": {
            "connected": state.decoder_status["aprs_is"]["connected"],
            "enabled": state.decoder_status["aprs_is"]["enabled"],
            "address": state.decoder_status["aprs_is"].get("address"),
            "last_packet_at": state.decoder_status["aprs_is"].get("last_packet_at"),
        },
        "rf": {
            "connected": state.decoder_status["direwolf_kiss"]["connected"],
            "enabled": state.decoder_status["direwolf_kiss"]["enabled"],
            "process_running": state.decoder_status["direwolf_kiss"]["process_running"],
        },
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

