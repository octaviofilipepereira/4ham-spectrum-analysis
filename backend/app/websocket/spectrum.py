"""
WebSocket handler for real-time spectrum waterfall data streaming.

Provides /ws/spectrum endpoint that streams FFT spectrum data with
mode markers, peak detection, and temporal persistence filtering.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, Any, Set
import numpy as np

from fastapi import APIRouter, WebSocket

from app.dependencies import state
from app.dependencies.helpers import (
    safe_float,
    log,
    hint_mode_by_frequency,
    frequency_within_scan_band
)
from app.dsp.pipeline import (
    apply_agc_smoothed,
    compute_fft_db,
    detect_peaks,
    estimate_noise_floor,
    estimate_occupancy,
    classify_mode_heuristic,
    encode_delta_int8
)

router = APIRouter()


@router.websocket("/ws/spectrum")
async def ws_spectrum(websocket: WebSocket) -> None:
    """
    Stream real-time spectrum waterfall data.
    
    Performs continuous FFT processing with advanced features:
    - FFT computation with smoothing
    - Peak detection
    - Noise floor estimation
    - Mode marker detection with temporal persistence
    - Optional delta compression (int8 encoding)
    - AGC (Automatic Gain Control) if enabled
    - Configurable frame rate
    
    Args:
        websocket: FastAPI WebSocket connection instance
        
    Message Format (uncompressed):
        {
            "spectrum_frame": {
                "timestamp": "2026-02-23T12:34:56.789Z",
                "center_hz": 14100000,
                "span_hz": 192000,
                "bin_hz": 93.75,
                "min_db": -120.0,
                "max_db": -40.0,
                "fft_db": [float array],
                "noise_floor_db": -95.5,
                "peaks": [
                    {"offset_hz": 1250.0, "power_db": -65.2},
                    ...
                ],
                "mode_markers": [
                    {
                        "offset_hz": 1200.0,
                        "frequency_hz": 14074000,
                        "mode": "FT8",
                        "snr_db": 15.3,
                        "bandwidth_hz": 2500,
                        "confidence": 0.92
                    },
                    ...
                ],
                "scan_start_hz": 14000000,
                "scan_end_hz": 14350000,
                "agc_gain_db": 12.5
            }
        }
        
    Message Format (compressed):
        - Same structure but fft_db replaced with:
          "baseline_db": float,
          "deltas_int8": [int8 array],
          "chunk_size": int
          
    Authentication:
        - If auth is enabled, verifies 'Authorization' header with Basic Auth
        - Closes connection with code 1008 if authentication fails
        
    Mode Markers:
        - Only FT8 and FT4 markers are shown
        - Quality gate: minimum SNR and confidence thresholds
        - Temporal persistence: requires multiple consecutive detections
        - Bucketed by 1 kHz slots to tolerate frequency drift
        - Limited to 24 markers per frame
        - Stale markers expired after configurable timeout
        
    Performance:
        - Configurable FPS (default: varies by state.ws_spectrum_fps)
        - Timeout protection on send operations
        - Drop statistics tracking
        - Frame timing instrumentation
        
    Compression:
        - Enabled via state.ws_compress_spectrum flag
        - Uses delta + int8 encoding for bandwidth reduction
    """
    # Authenticate before accepting connection
    if state.auth_required and not state.verify_basic_auth_header(
        websocket.headers.get("authorization")
    ):
        await websocket.close(code=1008)
        return
    
    await websocket.accept()
    
    while True:
        frame_start = time.time()
        
        # Read IQ samples (use synthetic noise if unavailable)
        iq = state.scan_engine.read_iq(2048)
        if iq is None:
            iq = (np.random.randn(2048) + 1j * np.random.randn(2048)) * 0.02
        
        agc_gain_db = None
        
        # Apply AGC if enabled
        if state.agc_enabled:
            iq, agc_gain_db = apply_agc_smoothed(
                iq,
                state.agc_state,
                target_rms=state.agc_target_rms,
                max_gain_db=state.agc_max_gain_db,
                alpha=state.agc_alpha
            )
            state.last_agc_gain_db = agc_gain_db
        
        # Compute FFT spectrum
        fft_db, bin_hz, min_db, max_db = compute_fft_db(
            iq,
            state.scan_engine.sample_rate,
            smooth_bins=6
        )
        
        # Detect peaks
        peaks = detect_peaks(fft_db, bin_hz)
        
        # Estimate noise floor
        noise_floor_db = estimate_noise_floor(fft_db)
        threshold_dbm = (
            (noise_floor_db + state.snr_threshold_db) 
            if noise_floor_db is not None 
            else -95.0
        )
        
        # Detect occupancy segments
        occupancy_segments = estimate_occupancy(
            iq,
            state.scan_engine.sample_rate,
            threshold_dbm=threshold_dbm,
            adapt=False,
            snr_threshold_db=state.snr_threshold_db,
            min_bw_hz=state.min_bw_hz
        )
        
        # Process mode markers with temporal persistence
        mode_markers = []
        band_name = (
            state.scan_engine.config.get("band") 
            if state.scan_engine.config 
            else None
        )
        center_hz = float(state.scan_engine.center_hz or 0.0)
        now_ts = time.time()
        
        # Expire stale candidates from persistence tracker
        stale_keys = [
            k for k, v in state.marker_candidates.items()
            if now_ts - v["last_seen"] > state.marker_max_age_s
        ]
        for k in stale_keys:
            state.marker_candidates.pop(k, None)
        
        seen_keys: Set[int] = set()
        
        for segment in occupancy_segments:
            offset_hz = float(segment.get("offset_hz") or 0.0)
            bandwidth_hz = int(segment.get("bandwidth_hz") or 0)
            snr_db = float(segment.get("snr_db") or 0.0)
            frequency_hz = (
                int(round(center_hz + offset_hz)) 
                if center_hz > 0 
                else None
            )
            
            # Classify mode
            mode_name, mode_confidence = classify_mode_heuristic(
                bandwidth_hz,
                segment.get("snr_db")
            )
            
            # Refine generic DSP mode with specific digital protocol
            # when frequency falls in known FT8/FT4/WSPR window
            freq_hint = hint_mode_by_frequency(
                frequency_hz,
                band_name=band_name,
                bandwidth_hz=bandwidth_hz
            )
            if freq_hint:
                mode_name = freq_hint
            
            # Filter: must be within scan band
            if not frequency_within_scan_band(
                frequency_hz,
                bandwidth_hz=bandwidth_hz
            ):
                continue
            
            # Filter: only show FT8 / FT4 markers (all others discarded)
            if mode_name not in ("FT8", "FT4"):
                continue
            
            # Quality gate: filter weak / low-confidence detections
            if snr_db < state.marker_min_snr_db:
                continue
            if mode_confidence < state.marker_min_confidence:
                continue
            
            # Temporal persistence: require repeated detections
            # Bucket by 1 kHz-wide frequency slot to tolerate small drift
            bucket_key = int(round((frequency_hz or 0) / 1000))
            seen_keys.add(bucket_key)
            
            cand = state.marker_candidates.get(bucket_key)
            
            if cand is None:
                # New candidate
                state.marker_candidates[bucket_key] = {
                    "hits": 1,
                    "last_seen": now_ts,
                    "marker": {
                        "offset_hz": offset_hz,
                        "frequency_hz": frequency_hz,
                        "mode": mode_name,
                        "snr_db": snr_db,
                        "bandwidth_hz": bandwidth_hz,
                        "confidence": float(mode_confidence),
                    },
                }
                
                # Show immediately if minimum hits threshold is 1
                if state.marker_min_hits <= 1:
                    mode_markers.append(
                        state.marker_candidates[bucket_key]["marker"]
                    )
                continue
            
            # Update existing candidate
            cand["hits"] += 1
            cand["last_seen"] = now_ts
            cand["marker"] = {
                "offset_hz": offset_hz,
                "frequency_hz": frequency_hz,
                "mode": mode_name,
                "snr_db": snr_db,
                "bandwidth_hz": bandwidth_hz,
                "confidence": float(mode_confidence),
            }
            
            # Include marker if it has enough hits
            if cand["hits"] >= state.marker_min_hits:
                mode_markers.append(cand["marker"])
        
        # Sort markers by offset and limit to 24
        mode_markers.sort(key=lambda item: item.get("offset_hz", 0.0))
        mode_markers = mode_markers[:24]
        
        # Determine scan boundaries
        scan_start_hz = None
        scan_end_hz = None
        if state.scan_engine.config:
            scan_start_hz = int(
                safe_float(state.scan_engine.config.get("start_hz"), default=0) or 0
            )
            scan_end_hz = int(
                safe_float(state.scan_engine.config.get("end_hz"), default=0) or 0
            )
            
            if (
                scan_start_hz <= 0 
                or scan_end_hz <= 0 
                or scan_end_hz <= scan_start_hz
            ):
                scan_start_hz = None
                scan_end_hz = None
        
        # Update frame timestamp
        state.last_frame_ts = time.time()
        
        # Update spectrum cache
        state.spectrum_cache.update({
            "fft_db": fft_db,
            "bin_hz": bin_hz,
            "min_db": min_db,
            "max_db": max_db,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "center_hz": state.scan_engine.center_hz,
            "span_hz": state.scan_engine.sample_rate
        })
        
        # Build payload
        payload: Dict[str, Any] = {
            "spectrum_frame": {
                "timestamp": state.spectrum_cache["timestamp"],
                "center_hz": state.spectrum_cache["center_hz"],
                "span_hz": state.spectrum_cache["span_hz"],
                "bin_hz": bin_hz,
                "min_db": min_db,
                "max_db": max_db,
                "noise_floor_db": noise_floor_db,
                "peaks": peaks,
                "mode_markers": mode_markers,
                "scan_start_hz": scan_start_hz,
                "scan_end_hz": scan_end_hz,
                "agc_gain_db": agc_gain_db
            }
        }
        
        # Apply compression if enabled
        if state.ws_compress_spectrum:
            payload["spectrum_frame"].update(encode_delta_int8(fft_db))
        else:
            payload["spectrum_frame"]["fft_db"] = fft_db
        
        # Send with timeout protection
        try:
            await asyncio.wait_for(
                websocket.send_json(payload),
                timeout=state.ws_send_timeout_s
            )
            state.spectrum_send_stats["sent"] += 1
        except asyncio.TimeoutError:
            state.spectrum_send_stats["dropped"] += 1
            log("ws_spectrum_drop send_timeout")
        
        # Update last send timestamp
        state.last_send_ts = time.time()
        
        # Frame rate control
        elapsed = time.time() - frame_start
        period = 1.0 / state.ws_spectrum_fps
        delay = max(0.0, period - elapsed)
        await asyncio.sleep(delay)
