# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Scan API endpoints

"""
Scan API
========
Spectrum scan control and status endpoints.
"""

import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config.loader import (
    ConfigError,
    apply_region_profile_to_scan,
    load_region_profile,
    load_scan_request,
)
from app.dependencies import state
from app.dependencies.auth import verify_basic_auth, optional_verify_basic_auth
from app.dependencies.helpers import log, fallback_sample_rate_for_device
from app.scan.rotation import RotationConfig, RotationSlot, ScanRotation
from app.scan.preset_scheduler import PresetScheduler, _hhmm_to_minutes, _time_in_window
from app.api.decoders import (
    _start_cw_decoder,
    _stop_cw_decoder,
    _start_ft_external_decoder,
    _stop_ft_external_decoder,
    _start_ssb_detector,
    _stop_ssb_detector,
    _start_kiss_loop,
    _stop_kiss_loop,
)


router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


_CW_SUBBANDS_HZ = {
    "160m": (1_800_000, 1_840_000),
    "80m": (3_500_000, 3_600_000),
    "40m": (7_000_000, 7_040_000),
    "30m": (10_100_000, 10_130_000),
    "20m": (14_000_000, 14_070_000),
    "17m": (18_068_000, 18_095_000),  # exclusive CW ends at 18.095; 18.095-18.111 is narrow/all-modes
    "15m": (21_000_000, 21_150_000),
    "12m": (24_890_000, 24_930_000),
    "10m": (28_000_000, 28_300_000),
}

_SSB_SUBBANDS_HZ = {
    "160m": (1_843_000, 2_000_000),
    "80m": (3_600_000, 3_800_000),
    "40m": (7_090_000, 7_200_000),
    "20m": (14_140_000, 14_350_000),
    "17m": (18_100_000, 18_168_000),
    "15m": (21_160_000, 21_450_000),
    "12m": (24_930_000, 24_990_000),
    "10m": (28_300_000, 29_700_000),
}

_DEFAULT_BAND_BOUNDS_HZ = {
    "160m": (1_810_000, 2_000_000),
    "80m": (3_500_000, 3_800_000),
    "60m": (5_250_000, 5_450_000),
    "40m": (7_000_000, 7_200_000),
    "30m": (10_100_000, 10_150_000),
    "20m": (14_000_000, 14_350_000),
    "17m": (18_068_000, 18_168_000),
    "15m": (21_000_000, 21_450_000),
    "12m": (24_890_000, 24_990_000),
    "10m": (28_000_000, 29_700_000),
    "6m": (50_000_000, 54_000_000),
    "2m": (144_000_000, 146_000_000),
    "70cm": (430_000_000, 440_000_000),
}


def _resolve_cw_sweep_bounds(
    band_name: str,
    start_hz: int,
    end_hz: int,
) -> tuple[int, int]:
    band = str(band_name or "").strip().lower()
    cw_bounds = _CW_SUBBANDS_HZ.get(band)
    if not cw_bounds:
        return int(start_hz), int(end_hz)

    cw_start, cw_end = cw_bounds
    clipped_start = max(int(start_hz), int(cw_start))
    clipped_end = min(int(end_hz), int(cw_end))

    if clipped_end <= clipped_start:
        return int(start_hz), int(end_hz)
    return int(clipped_start), int(clipped_end)


def _resolve_ssb_bounds(
    band_name: str,
    start_hz: int,
    end_hz: int,
) -> tuple[int, int]:
    band = str(band_name or "").strip().lower()
    ssb_bounds = _SSB_SUBBANDS_HZ.get(band)
    if not ssb_bounds:
        return int(start_hz), int(end_hz)

    ssb_start, ssb_end = ssb_bounds
    clipped_start = max(int(start_hz), int(ssb_start))
    clipped_end = min(int(end_hz), int(ssb_end))
    if clipped_end <= clipped_start:
        return int(start_hz), int(end_hz)
    return int(clipped_start), int(clipped_end)


def _lookup_band_bounds(band_name: str) -> tuple[Optional[int], Optional[int]]:
    band = str(band_name or "").strip().lower()
    if not band:
        return None, None

    for band_entry in state.db.get_bands():
        if str(band_entry.get("name", "")).strip().lower() != band:
            continue
        band_start_hz = int(band_entry.get("start_hz", 0) or 0)
        band_end_hz = int(band_entry.get("end_hz", 0) or 0)
        if band_start_hz > 0 and band_end_hz > band_start_hz:
            return band_start_hz, band_end_hz
        break

    default_bounds = _DEFAULT_BAND_BOUNDS_HZ.get(band)
    if default_bounds:
        return int(default_bounds[0]), int(default_bounds[1])

    return None, None


def _resolve_band_display_bounds(
    band_name: str,
    start_hz: int,
    end_hz: int,
) -> tuple[Optional[int], Optional[int]]:
    band_start_hz, band_end_hz = _lookup_band_bounds(band_name)
    if band_start_hz is not None and band_end_hz is not None:
        return band_start_hz, band_end_hz

    requested_start_hz = int(start_hz or 0)
    requested_end_hz = int(end_hz or 0)
    if requested_start_hz > 0 and requested_end_hz > requested_start_hz:
        return requested_start_hz, requested_end_hz
    return None, None


@router.post("/start")
@limiter.limit("10/minute")  # Rate limit: 10 scan starts per minute
async def scan_start(payload: dict, request: Request, _: None = Depends(verify_basic_auth)) -> Dict:
    """
    Start a spectrum scan.
    
    Validates scan configuration, applies region profile if provided,
    resolves band frequencies from database, and starts the scan engine.
    
    Includes automatic sample rate fallback on device errors.
    
    Args:
        payload: Scan configuration dict with keys:
            - scan: Scan parameters (device_id, start_hz, end_hz, sample_rate, etc.)
            - device: Device type selection
            - region_profile_path: Optional region profile path
            
    Returns:
        Scan state dict with scan_id and status
        
    Raises:
        HTTPException: 400 if config invalid, 500 if scan fails to start
    """
    # Validate and normalize payload
    try:
        normalized_payload = load_scan_request(payload)
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scan = normalized_payload.get("scan", {})
    selected_device = normalized_payload.get("device")
    
    # Set device_id if not provided
    if selected_device and not scan.get("device_id"):
        scan["device_id"] = selected_device
    
    # Apply region profile if provided
    region_profile_path = normalized_payload.get("region_profile_path")
    if region_profile_path:
        try:
            region_profile = load_region_profile(region_profile_path)
            apply_region_profile_to_scan(scan, region_profile)
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Resolve band frequencies from database if band name provided
    if scan.get("band"):
        start_hz = int(scan.get("start_hz", 0) or 0)
        end_hz = int(scan.get("end_hz", 0) or 0)
        band_start_hz, band_end_hz = _lookup_band_bounds(scan.get("band"))

        if start_hz <= 0 and band_start_hz is not None:
            scan["start_hz"] = band_start_hz
        if end_hz <= 0 and band_end_hz is not None:
            scan["end_hz"] = band_end_hz

    band_display_start_hz, band_display_end_hz = _resolve_band_display_bounds(
        scan.get("band"),
        scan.get("start_hz", 0),
        scan.get("end_hz", 0),
    )
    if band_display_start_hz is not None and band_display_end_hz is not None:
        scan["band_display_start_hz"] = band_display_start_hz
        scan["band_display_end_hz"] = band_display_end_hz

    # Validate frequency range
    start_hz = int(scan.get("start_hz", 0) or 0)
    end_hz = int(scan.get("end_hz", 0) or 0)

    # Enforce mode-specific SSB subband limits before validation.
    decoder_mode = normalized_payload.get("decoder_mode", "").lower()
    if decoder_mode == "ssb":
        clipped_start_hz, clipped_end_hz = _resolve_ssb_bounds(
            scan.get("band"),
            start_hz,
            end_hz,
        )
        scan["start_hz"] = clipped_start_hz
        scan["end_hz"] = clipped_end_hz
        # Update band_display to match SSB subband so the VFO center is correct
        scan["band_display_start_hz"] = clipped_start_hz
        scan["band_display_end_hz"] = clipped_end_hz
        # Candidate-focus SSB scanning: keep fast sweep, but hold longer when
        # repeated occupancy candidates are detected on the current block.
        scan.setdefault("ssb_focus_enable", True)
        scan.setdefault("ssb_focus_hold_ms", 10000)
        scan.setdefault("ssb_focus_hits_required", 2)
        scan.setdefault("ssb_focus_candidate_ttl_s", 25.0)
        scan.setdefault("ssb_focus_cooldown_s", 20.0)
        scan.setdefault("ssb_focus_bucket_hz", 2000)
        # NOTE: ssb_focus_max_holds_per_pass is intentionally NOT set here.
        # The engine computes it adaptively (~1 hold per 15 kHz of scan span,
        # min 4, max 16).  If the frontend sends an explicit value it will be
        # honoured as an override.
        start_hz = clipped_start_hz
        end_hz = clipped_end_hz

    if start_hz <= 0 or end_hz <= 0 or end_hz <= start_hz:
        raise HTTPException(status_code=400, detail="Invalid scan range for selected band")

    # Store selected decoder mode in scan state and start appropriate decoder
    if decoder_mode:
        state.scan_state["decoder_mode"] = decoder_mode
        log(f"scan_decoder_mode:{decoder_mode}")
        
        # Define mode categories
        ft_modes = ["ft8", "ft4", "wspr"]
        cw_modes = ["cw"]
        
        if decoder_mode in cw_modes:
            # CW mode: stop FT decoder, start CW decoder
            if state.ft_external_decoder is not None:
                await _stop_ft_external_decoder()
                log("scan_ft_external_decoder_stopped:switching_to_cw_mode")
            await _stop_ssb_detector()
            cw_start_hz, cw_end_hz = _resolve_cw_sweep_bounds(
                scan.get("band"),
                start_hz,
                end_hz,
            )
            # Apply per-scan CW sweep parameters from payload (overrides env defaults)
            _cw_step = normalized_payload.get("cw_step_hz")
            _cw_dwell = normalized_payload.get("cw_dwell_s")
            _cw_params_changed = False
            _cw_band_changed = False
            if _cw_step is not None:
                try:
                    _new_step = int(_cw_step)
                    if _new_step != state.cw_sweep_step_hz:
                        state.cw_sweep_step_hz = _new_step
                        _cw_params_changed = True
                except (ValueError, TypeError):
                    pass
            if _cw_dwell is not None:
                try:
                    _new_dwell = float(_cw_dwell)
                    if _new_dwell != state.cw_sweep_dwell_s:
                        state.cw_sweep_dwell_s = _new_dwell
                        _cw_params_changed = True
                except (ValueError, TypeError):
                    pass
            # Restart decoder if scan band changed (so sweep bounds match band)
            if state.cw_decoder is not None:
                try:
                    _snap = state.cw_decoder.snapshot() or {}
                    _current_start = int(_snap.get("band_start_hz") or 0)
                    _current_end = int(_snap.get("band_end_hz") or 0)
                    _cw_band_changed = (
                        _current_start != cw_start_hz or _current_end != cw_end_hz
                    )
                except Exception:
                    _cw_band_changed = False

            # Restart decoder if params or band changed
            if state.cw_decoder and (_cw_params_changed or _cw_band_changed):
                await _stop_cw_decoder()
                log(
                    f"scan_cw_decoder_restarted:step={state.cw_sweep_step_hz}hz "
                    f"dwell={state.cw_sweep_dwell_s}s "
                    f"band={cw_start_hz}-{cw_end_hz} "
                    f"params_changed={_cw_params_changed} band_changed={_cw_band_changed}"
                )
            if not state.cw_decoder:
                result = await _start_cw_decoder(
                    force=True,
                    band_start_hz=cw_start_hz,
                    band_end_hz=cw_end_hz,
                )
                log(f"scan_cw_decoder_started:{result}")
        elif decoder_mode in ft_modes:
            # FT mode: stop CW decoder, start/configure FT decoder
            if state.cw_decoder is not None:
                await _stop_cw_decoder()
                log("scan_cw_decoder_stopped:switching_to_ft_mode")
            await _stop_ssb_detector()
            decoder_mode_upper = decoder_mode.upper()
            # FT8 and FT4 share the same frequency segments — always
            # decode both so that events from either sub-mode are captured.
            if decoder_mode_upper in ("FT8", "FT4"):
                active_modes = ["FT8", "FT4"]
            else:
                active_modes = [decoder_mode_upper]
            if state.ft_external_decoder is not None:
                state.ft_external_decoder.set_modes(active_modes)
            else:
                result = await _start_ft_external_decoder(force=True)
                log(f"scan_ft_external_decoder_started:{result}")
                if state.ft_external_decoder:
                    state.ft_external_decoder.set_modes(active_modes)
            state.ft_external_modes[:] = active_modes
        else:
            # Other modes (SSB, APRS): stop FT/CW and start mode-specific decoder
            if state.cw_decoder is not None:
                await _stop_cw_decoder()
            if state.ft_external_decoder is not None:
                await _stop_ft_external_decoder()
            if decoder_mode == "ssb":
                await _stop_kiss_loop()
                result = await _start_ssb_detector(force=True)
                log(f"scan_ssb_detector_started:{result}")
            elif decoder_mode == "aprs":
                await _stop_ssb_detector()
                # Stop KISS loop pre-scan so it can be restarted with the
                # IQ→FM demodulator after the scan engine is running.
                if state.kiss_task is not None:
                    await _stop_kiss_loop()
            else:
                await _stop_ssb_detector()
                await _stop_kiss_loop()

    # If device is open in preview mode, close it so the scan can take over.
    state.scan_engine.preview_close()

    # Pre-check: ensure at least one real SDR device is connected.
    # Audio devices (SoapySDR audio plugin) are excluded — they are
    # host sound cards, not SDR receivers.
    try:
        all_devices = state.controller.list_devices()
        available_devices = [
            d for d in all_devices
            if str(d.get("type", "")).lower() not in ("audio",)
        ]
    except Exception:
        available_devices = []
    if not available_devices:
        raise HTTPException(
            status_code=422,
            detail="No SDR device detected. Connect your device and try again."
        )

    # Start scan with automatic sample rate fallback
    try:
        try:
            await state.scan_engine.start_async(scan)
        except Exception as exc:
            message = str(exc)
            # Retry with fallback sample rate if setSampleRate failed
            if "setSampleRate failed" not in message:
                raise
            
            fallback_rate = fallback_sample_rate_for_device(
                scan.get("device_id") or selected_device,
                scan.get("sample_rate"),
            )
            if not fallback_rate:
                raise
            
            previous_rate = int(scan.get("sample_rate", 0) or 0)
            scan["sample_rate"] = fallback_rate
            log(f"scan_start_retry_sample_rate:{previous_rate}->{fallback_rate}")
            await state.scan_engine.start_async(scan)

        # Update scan state
        state.scan_state["state"] = "running"
        state.scan_state["device"] = normalized_payload.get("device", "rtl_sdr")
        state.scan_state["started_at"] = datetime.now(timezone.utc).isoformat()
        state.scan_state["scan"] = scan
        state.scan_state["scan_id"] = state.db.start_scan(scan, state.scan_state["started_at"])
        
        # Start APRS KISS loop now that the scan engine is running,
        # so the IQ→FM demodulator can register as an IQ listener.
        if decoder_mode == "aprs":
            result = await _start_kiss_loop(force=True)
            log(f"scan_kiss_loop_started:{result}")

        log("scan_start")
        return state.scan_state
        
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start scan: {exc}") from exc


@router.post("/stop")
async def scan_stop(_: None = Depends(verify_basic_auth)) -> Dict:
    """
    Stop the currently running scan.
    
    Stops the scan engine and updates scan state in database.
    
    Returns:
        Updated scan state dict
    """
    await state.scan_engine.stop_async()
    await _stop_ssb_detector()
    # Stop rotation if active
    if state.scan_rotation and state.scan_rotation.running:
        await state.scan_rotation.stop()
        state.scan_rotation = None
    state.scan_state["state"] = "stopped"
    state.scan_state["decoder_mode"] = ""  # clear so frontend doesn't auto-select the button
    # Clear voice marker cache to prevent stale SSB VOICE DETECTED markers
    # from polluting the waterfall when switching modes (e.g., CW → SSB)
    state.voice_marker_cache.clear()
    # Drop stale scan bounds from the previous run. Keeping this payload while
    # entering preview can make the spectrum ruler use an old narrow test range
    # (for example 7.073-7.075 MHz) instead of the preview band limits.
    state.scan_state["scan"] = None
    state.db.end_scan(
        state.scan_state.get("scan_id"),
        datetime.now(timezone.utc).isoformat()
    )
    log("scan_stop")
    # Reopen preview mode after scan stops if a real SDR device is available
    try:
        sdr_devices = [
            d for d in state.controller.list_devices()
            if str(d.get("type", "")).lower() not in ("audio",)
        ]
        if sdr_devices:
            preview_sr = int(os.getenv("PREVIEW_SAMPLE_RATE", "2048000"))
            preview_hz = int(os.getenv("PREVIEW_CENTER_HZ", "14175000"))
            preview_start = int(os.getenv("PREVIEW_START_HZ", "14000000"))
            preview_end = int(os.getenv("PREVIEW_END_HZ", "14350000"))
            opened = await state.scan_engine.preview_open(
                device_id=sdr_devices[0]["id"],
                sample_rate=preview_sr,
                center_hz=preview_hz,
                start_hz=preview_start,
                end_hz=preview_end,
            )
            if opened:
                state.scan_state["state"] = "preview"
                state.scan_state["scan"] = {
                    "band": "20m",
                    "center_hz": preview_hz,
                    "start_hz": preview_start,
                    "end_hz": preview_end,
                    "sample_rate": preview_sr,
                    "mode": "fixed",
                }
    except Exception:
        pass
    return state.scan_state


@router.post("/preview/tune")
async def preview_tune(payload: dict, _: None = Depends(verify_basic_auth)) -> Dict:
    """
    Retune the SDR device while in preview (monitor) mode.

    Closes the current preview stream and reopens it at the requested
    centre frequency, allowing the user to switch bands without starting
    a full scan.

    Args:
        payload: Dict with keys:
            - center_hz (int, required): New centre frequency in Hz
            - band      (str, optional): Band name for logging

    Returns:
        Updated scan state dict

    Raises:
        HTTPException: 422 if no SDR device available or not in preview mode
    """
    center_hz = int(payload.get("center_hz") or 0)
    if center_hz <= 0:
        raise HTTPException(status_code=422, detail="center_hz must be a positive integer")

    sdr_devices = [
        d for d in state.controller.list_devices()
        if str(d.get("type", "")).lower() not in ("audio",)
    ]
    if not sdr_devices:
        raise HTTPException(status_code=422, detail="No SDR device detected")

    # Close existing preview (no-op if already closed)
    state.scan_engine.preview_close()

    preview_sr = int(os.getenv("PREVIEW_SAMPLE_RATE", "2048000"))
    # Accept explicit band boundaries so the WS frames carry the correct
    # scan_start_hz / scan_end_hz — identical to what scan mode sends.
    band_start_hz = int(payload.get("start_hz") or 0)
    band_end_hz = int(payload.get("end_hz") or 0)
    opened = await state.scan_engine.preview_open(
        device_id=sdr_devices[0]["id"],
        sample_rate=preview_sr,
        center_hz=center_hz,
        start_hz=band_start_hz,
        end_hz=band_end_hz,
    )
    if not opened:
        raise HTTPException(status_code=500, detail="Failed to retune SDR device")

    state.scan_state["state"] = "preview"
    band = str(payload.get("band") or "")
    log(f"preview_tune center_hz={center_hz}" + (f" band={band}" if band else ""))
    return state.scan_state


@router.post("/mode")
async def change_decoder_mode(payload: dict, _: None = Depends(verify_basic_auth)) -> Dict:
    """
    Change decoder mode during active scan.
    
    Allows switching between decoders (FT8, FT4, WSPR, etc.) without stopping the scan.
    Updates scan_state with new decoder_mode for decoder selection.
    
    Implements mutual exclusion between decoders:
    - FT8/FT4/WSPR → FT external decoder active, CW decoder stopped
    - CW → CW decoder active, FT external decoder stopped
    - SSB/APRS → Both decoders stopped (use other decoders)
    
    Args:
        payload: Dict with key:
            - decoder_mode: New decoder mode (ft8, ft4, wspr, cw, ssb, aprs)
            
    Returns:
        Status dict with updated scan_state
    """
    decoder_mode = str(payload.get("decoder_mode", "")).strip().lower()
    if not decoder_mode:
        raise HTTPException(status_code=400, detail="decoder_mode is required")
    
    # Validate decoder mode is one of the supported modes
    valid_modes = ["ft8", "ft4", "wspr", "cw", "ssb", "aprs"]
    if decoder_mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"Invalid decoder_mode. Must be one of: {', '.join(valid_modes)}")
    
    # Define which modes use which decoder
    ft_modes = ["ft8", "ft4", "wspr"]
    cw_modes = ["cw"]
    
    # Update scan state with new decoder mode
    state.scan_state["decoder_mode"] = decoder_mode
    log(f"scan_decoder_mode_changed:{decoder_mode}")
    
    # Manage decoder lifecycle based on mode transition
    if decoder_mode in ft_modes:
        # FT8/FT4/WSPR mode: need FT external decoder, stop CW/SSB/KISS
        
        # Stop CW decoder if it's running
        if state.cw_decoder is not None:
            try:
                await _stop_cw_decoder()
                log("scan_cw_decoder_stopped:switching_to_ft_mode")
            except Exception as exc:
                log(f"scan_cw_decoder_stop_failed:{exc}")
        try:
            await _stop_ssb_detector()
        except Exception as exc:
            log(f"scan_ssb_detector_stop_failed:{exc}")
        try:
            await _stop_kiss_loop()
        except Exception as exc:
            log(f"scan_kiss_loop_stop_failed:{exc}")
        
        # Start FT external decoder if not already running
        if state.ft_external_decoder is None:
            try:
                result = await _start_ft_external_decoder(force=True)
                log(f"scan_ft_external_decoder_started:{result}")
            except Exception as exc:
                log(f"scan_ft_external_decoder_start_failed:{exc}")
        
        # Update FT decoder to process only the selected mode
        decoder_mode_upper = decoder_mode.upper()
        if state.ft_external_decoder is not None:
            state.ft_external_decoder.set_modes([decoder_mode_upper])
            state.ft_external_modes[:] = [decoder_mode_upper]
            log(f"scan_ft_external_modes_updated:{decoder_mode_upper}")
    
    elif decoder_mode in cw_modes:
        # CW mode: need CW decoder, stop FT/SSB/KISS
        
        # Stop FT external decoder if it's running
        if state.ft_external_decoder is not None:
            try:
                await _stop_ft_external_decoder()
                log("scan_ft_external_decoder_stopped:switching_to_cw_mode")
            except Exception as exc:
                log(f"scan_ft_external_decoder_stop_failed:{exc}")
        try:
            await _stop_ssb_detector()
        except Exception as exc:
            log(f"scan_ssb_detector_stop_failed:{exc}")
        try:
            await _stop_kiss_loop()
        except Exception as exc:
            log(f"scan_kiss_loop_stop_failed:{exc}")

        current_scan = dict(state.scan_state.get("scan") or {})
        cw_start_hz, cw_end_hz = _resolve_cw_sweep_bounds(
            current_scan.get("band"),
            int(current_scan.get("start_hz", 0) or 0),
            int(current_scan.get("end_hz", 0) or 0),
        )
        
        # Start CW decoder if not already running
        if state.cw_decoder is None:
            try:
                result = await _start_cw_decoder(
                    force=True,
                    band_start_hz=cw_start_hz,
                    band_end_hz=cw_end_hz,
                )
                log(f"scan_cw_decoder_started:{result}")
            except Exception as exc:
                log(f"scan_cw_decoder_start_failed:{exc}")
    
    else:
        # SSB/APRS mode: stop FT/CW decoders; start mode-specific decoder
        
        # Stop CW decoder if running
        if state.cw_decoder is not None:
            try:
                await _stop_cw_decoder()
                log("scan_cw_decoder_stopped:switching_to_other_mode")
            except Exception as exc:
                log(f"scan_cw_decoder_stop_failed:{exc}")
        
        # Stop FT external decoder if running
        if state.ft_external_decoder is not None:
            try:
                await _stop_ft_external_decoder()
                log("scan_ft_external_decoder_stopped:switching_to_other_mode")
            except Exception as exc:
                log(f"scan_ft_external_decoder_stop_failed:{exc}")

        if decoder_mode == "ssb":
            # Stop KISS loop if switching away from APRS
            try:
                await _stop_kiss_loop()
            except Exception as exc:
                log(f"scan_kiss_loop_stop_failed:{exc}")

            current_scan = dict(state.scan_state.get("scan") or {})
            scan_start_hz = int(current_scan.get("start_hz", 0) or 0)
            scan_end_hz = int(current_scan.get("end_hz", 0) or 0)
            clipped_start_hz, clipped_end_hz = _resolve_ssb_bounds(
                current_scan.get("band"),
                scan_start_hz,
                scan_end_hz,
            )
            needs_clip = (
                clipped_start_hz > 0
                and clipped_end_hz > clipped_start_hz
                and (clipped_start_hz != scan_start_hz or clipped_end_hz != scan_end_hz)
            )
            if needs_clip and state.scan_state.get("state") == "running":
                current_scan["start_hz"] = clipped_start_hz
                current_scan["end_hz"] = clipped_end_hz
                if int(current_scan.get("center_hz", 0) or 0) < clipped_start_hz:
                    current_scan["center_hz"] = clipped_start_hz
                await state.scan_engine.stop_async()
                await state.scan_engine.start_async(current_scan)
                state.scan_state["scan"] = current_scan
                log(
                    f"scan_ssb_range_clipped:{scan_start_hz}-{scan_end_hz}"
                    f"->{clipped_start_hz}-{clipped_end_hz}"
                )

            try:
                result = await _start_ssb_detector(force=True)
                log(f"scan_ssb_detector_started:{result}")
            except Exception as exc:
                log(f"scan_ssb_detector_start_failed:{exc}")

        elif decoder_mode == "aprs":
            # Stop SSB detector if switching away from SSB
            try:
                await _stop_ssb_detector()
            except Exception as exc:
                log(f"scan_ssb_detector_stop_failed:{exc}")

            try:
                result = await _start_kiss_loop(force=True)
                log(f"scan_kiss_loop_started:{result}")
            except Exception as exc:
                log(f"scan_kiss_loop_start_failed:{exc}")

        else:
            try:
                await _stop_ssb_detector()
            except Exception as exc:
                log(f"scan_ssb_detector_stop_failed:{exc}")
            try:
                await _stop_kiss_loop()
            except Exception as exc:
                log(f"scan_kiss_loop_stop_failed:{exc}")

    return {"status": "ok", "decoder_mode": decoder_mode}



@router.get("/status")
def scan_status(_: bool = Depends(optional_verify_basic_auth)) -> Dict:
    """
    Get current scan status.
    
    Returns scan state combined with engine status.
    Authentication is optional for this endpoint.
    
    Returns:
        Dict with scan state and engine status
    """
    payload = dict(state.scan_state)
    payload["engine"] = state.scan_engine.status()
    if state.scan_rotation:
        payload["rotation"] = state.scan_rotation.status()
    return payload


# Scans history endpoint (outside /scan prefix)
scans_router = APIRouter(prefix="/api", tags=["scan"])

@scans_router.get("/scans")
def scans(limit: int = 100, _: bool = Depends(optional_verify_basic_auth)) -> List[Dict]:
    """
    Get scan history.
    
    Returns list of past scans with metadata.
    Authentication is optional for this endpoint.
    
    Args:
        limit: Maximum number of scans to return (default: 100)
        
    Returns:
        List of scan records
    """
    return state.db.get_scans(limit=limit)


# ═══════════════════════════════════════════════════════════════════
# Scan Rotation endpoints
# ═══════════════════════════════════════════════════════════════════

async def _rotation_switch_slot(slot: RotationSlot) -> bool:
    """Callback invoked by ScanRotation when it's time to switch slot.

    Orchestrates:
    1. Stop current decoders
    2. Resolve band frequencies
    3. Restart scan at new band (if changed)
    4. Start the new decoder mode
    """
    current_scan = dict(state.scan_state.get("scan") or {})
    current_band = str(current_scan.get("band") or "").strip().lower()
    new_band = slot.band.strip().lower()
    new_mode = slot.mode.strip().lower()

    log(f"rotation_switch band={slot.band} mode={slot.mode}")

    # ── Resolve band bounds ──────────────────────────────────────
    band_start_hz, band_end_hz = _lookup_band_bounds(slot.band)
    if band_start_hz is None or band_end_hz is None:
        log(f"rotation_switch_failed:unknown_band={slot.band}")
        return False

    start_hz = band_start_hz
    end_hz = band_end_hz

    # Apply mode-specific subband clipping
    if new_mode == "cw":
        start_hz, end_hz = _resolve_cw_sweep_bounds(slot.band, start_hz, end_hz)
    elif new_mode == "ssb":
        start_hz, end_hz = _resolve_ssb_bounds(slot.band, start_hz, end_hz)

    # ── Band change: stop + restart scan engine ──────────────────
    band_changed = (current_band != new_band)
    freq_changed = (
        int(current_scan.get("start_hz", 0) or 0) != start_hz
        or int(current_scan.get("end_hz", 0) or 0) != end_hz
    )

    if band_changed or freq_changed:
        # Stop all decoders before restarting scan
        await _stop_ft_external_decoder()
        await _stop_cw_decoder()
        await _stop_ssb_detector()

        new_scan = dict(current_scan)
        new_scan["band"] = slot.band
        new_scan["start_hz"] = start_hz
        new_scan["end_hz"] = end_hz
        center_hz = (start_hz + end_hz) // 2
        new_scan["center_hz"] = center_hz

        # Band display bounds for frontend ruler
        display_start, display_end = _resolve_band_display_bounds(
            slot.band, start_hz, end_hz,
        )
        if display_start is not None and display_end is not None:
            new_scan["band_display_start_hz"] = display_start
            new_scan["band_display_end_hz"] = display_end

        # SSB focus params
        if new_mode == "ssb":
            new_scan["ssb_focus_enable"] = True
            new_scan.setdefault("ssb_focus_hold_ms", 10000)
            new_scan.setdefault("ssb_focus_hits_required", 2)
            new_scan.setdefault("ssb_focus_candidate_ttl_s", 25.0)
            new_scan.setdefault("ssb_focus_cooldown_s", 20.0)
            new_scan.setdefault("ssb_focus_bucket_hz", 2000)
        else:
            new_scan["ssb_focus_enable"] = False

        # Stop and restart scan engine (keeps SDR device open internally)
        await state.scan_engine.stop_async()
        await state.scan_engine.start_async(new_scan)

        state.scan_state["scan"] = new_scan
        state.scan_state["state"] = "running"
        state.scan_state["scan_id"] = state.db.start_scan(
            new_scan, datetime.now(timezone.utc).isoformat(),
        )
        log(f"rotation_scan_restarted band={slot.band} range={start_hz}-{end_hz}")
    else:
        # Same band/freqs — just stop old decoders
        await _stop_ft_external_decoder()
        await _stop_cw_decoder()
        await _stop_ssb_detector()

    # ── Start new decoder ────────────────────────────────────────
    state.scan_state["decoder_mode"] = new_mode
    ft_modes = ["ft8", "ft4", "wspr"]

    if new_mode in ft_modes:
        result = await _start_ft_external_decoder(force=True)
        if state.ft_external_decoder:
            state.ft_external_decoder.set_modes([new_mode.upper()])
        state.ft_external_modes[:] = [new_mode.upper()]
        log(f"rotation_decoder_started:ft:{new_mode} result={result}")
    elif new_mode == "cw":
        result = await _start_cw_decoder(
            force=True,
            band_start_hz=start_hz,
            band_end_hz=end_hz,
        )
        log(f"rotation_decoder_started:cw result={result}")
    elif new_mode == "ssb":
        result = await _start_ssb_detector(force=True)
        log(f"rotation_decoder_started:ssb result={result}")

    return True


@router.post("/rotation/start")
async def rotation_start(
    payload: dict,
    request: Request,
    _: None = Depends(verify_basic_auth),
) -> Dict:
    """Start scan rotation with the given slot configuration.

    Requires a running scan or will start one automatically.
    """
    # Stop any existing rotation
    if state.scan_rotation and state.scan_rotation.running:
        await state.scan_rotation.stop()
        state.scan_rotation = None

    # Parse rotation config
    try:
        config = RotationConfig.from_dict(payload)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # If no scan is running, start one on the first slot
    if state.scan_state.get("state") != "running":
        first = config.slots[0]
        band_start, band_end = _lookup_band_bounds(first.band)
        if band_start is None or band_end is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown band: {first.band}",
            )

        # Reuse device from last scan state if available;
        # otherwise omit — controller auto-selects first real SDR.
        prev_device = (
            state.scan_state.get("device")
            or (state.scan_state.get("scan") or {}).get("device_id")
        )

        # Build a minimal scan payload for the first slot
        scan_payload = {
            "scan": {
                "band": first.band,
                "start_hz": band_start,
                "end_hz": band_end,
                "center_hz": (band_start + band_end) // 2,
                "step_hz": 2000,
                "dwell_ms": 250,
                "sample_rate": 2048000,
                "mode": "auto",
            },
            "decoder_mode": first.mode,
        }
        if prev_device:
            scan_payload["device"] = prev_device
        # Use the regular scan_start to initialise everything properly
        await scan_start(scan_payload, request, _)

    # Create and start rotation
    rotation = ScanRotation(config, _rotation_switch_slot)
    state.scan_rotation = rotation
    started = await rotation.start()
    if not started:
        raise HTTPException(status_code=500, detail="Failed to start rotation")

    log(f"rotation_started slots={len(config.slots)}")
    return rotation.status()


@router.post("/rotation/stop")
async def rotation_stop(_: None = Depends(verify_basic_auth)) -> Dict:
    """Stop scan rotation and the active scan, releasing the SDR device."""
    if not state.scan_rotation or not state.scan_rotation.running:
        raise HTTPException(status_code=400, detail="No rotation is running")

    await state.scan_rotation.stop()
    # Stop all decoders that might be running
    await _stop_ft_external_decoder()
    await _stop_cw_decoder()
    await _stop_ssb_detector()
    # Stop the active scan to release the SDR device
    await state.scan_engine.stop_async()
    state.scan_state["state"] = "stopped"
    state.scan_state["decoder_mode"] = ""
    state.scan_state["scan"] = None
    state.scan_state["device"] = None
    state.voice_marker_cache.clear()
    state.db.end_scan(
        state.scan_state.get("scan_id"),
        datetime.now(timezone.utc).isoformat()
    )

    status = state.scan_rotation.status()
    log("rotation_stopped")

    # Reopen preview mode so the waterfall keeps showing data
    try:
        sdr_devices = [
            d for d in state.controller.list_devices()
            if str(d.get("type", "")).lower() not in ("audio",)
        ]
        if sdr_devices:
            preview_sr = int(os.getenv("PREVIEW_SAMPLE_RATE", "2048000"))
            preview_hz = int(os.getenv("PREVIEW_CENTER_HZ", "14175000"))
            preview_start = int(os.getenv("PREVIEW_START_HZ", "14000000"))
            preview_end = int(os.getenv("PREVIEW_END_HZ", "14350000"))
            opened = await state.scan_engine.preview_open(
                device_id=sdr_devices[0]["id"],
                sample_rate=preview_sr,
                center_hz=preview_hz,
                start_hz=preview_start,
                end_hz=preview_end,
            )
            if opened:
                state.scan_state["state"] = "preview"
                state.scan_state["scan"] = {
                    "band": "20m",
                    "center_hz": preview_hz,
                    "start_hz": preview_start,
                    "end_hz": preview_end,
                    "sample_rate": preview_sr,
                    "mode": "fixed",
                }
    except Exception:
        pass

    return status


@router.get("/rotation/status")
def rotation_status(
    _: bool = Depends(optional_verify_basic_auth),
) -> Dict:
    """Get rotation status (current slot, time remaining, full config)."""
    if not state.scan_rotation:
        return {"running": False}
    return state.scan_rotation.status()


# ── Rotation Presets CRUD ──────────────────────────────────────

@router.get("/rotation/presets")
def list_rotation_presets(
    _: bool = Depends(optional_verify_basic_auth),
) -> List[Dict]:
    """List all saved rotation presets."""
    return state.db.get_rotation_presets()


@router.post("/rotation/presets")
def create_rotation_preset(
    body: Dict,
    _: None = Depends(verify_basic_auth),
) -> Dict:
    """Save a new rotation preset."""
    name = str(body.get("name") or "").strip()
    config = body.get("config")
    if not name:
        raise HTTPException(status_code=400, detail="Preset name is required")
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="Preset config is required")
    return state.db.save_rotation_preset(name, config)


@router.delete("/rotation/presets/{preset_id}")
def delete_rotation_preset(
    preset_id: int,
    _: None = Depends(verify_basic_auth),
) -> Dict:
    """Delete a rotation preset by ID."""
    if not state.db.delete_rotation_preset(preset_id):
        raise HTTPException(status_code=404, detail="Preset not found")
    return {"ok": True}


# ── Preset Schedule (time-of-day rotation of presets) ──────────

import re

_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _windows_overlap(s1: int, e1: int, s2: int, e2: int) -> bool:
    """Check if two circular time windows (in minutes 0–1439) overlap.

    Each window runs from start (inclusive) to end (exclusive) and may
    wrap around midnight.
    """
    # Expand each window to a set of minute-ranges on a 0–2879 number line
    # (doubling the day avoids modular arithmetic edge cases).
    def _ranges(s: int, e: int) -> list[tuple[int, int]]:
        if s < e:
            return [(s, e)]
        # cross-midnight: split into [s, 1440) + [0, e)
        return [(s, 1440), (0, e)]

    for a_start, a_end in _ranges(s1, e1):
        for b_start, b_end in _ranges(s2, e2):
            if a_start < b_end and b_start < a_end:
                return True
    return False


async def _apply_preset_by_id(preset_id: int) -> bool:
    """Load a rotation preset from DB and (re)start scan rotation with it.

    Called by the PresetScheduler background task when a time-window
    boundary is reached.
    """
    presets = state.db.get_rotation_presets()
    preset = next((p for p in presets if p["id"] == preset_id), None)
    if not preset:
        log(f"preset_scheduler:preset_not_found id={preset_id}")
        return False

    cfg = preset["config"]

    # Build the payload that RotationConfig.from_dict expects
    rotation_mode = cfg.get("rotationMode", "bands")
    dwell_s = int(cfg.get("dwell", 60) or 60)
    do_loop = cfg.get("loop", True)

    if rotation_mode == "modes":
        payload = {
            "rotation_mode": "modes",
            "band": cfg.get("band", "20m"),
            "dwell_s": dwell_s,
            "loop": do_loop,
            "modes": [s.get("mode", "ft8").lower() for s in cfg.get("slots", [])],
        }
    else:
        payload = {
            "rotation_mode": "bands",
            "dwell_s": dwell_s,
            "loop": do_loop,
            "slots": [
                {
                    "band": s.get("band", "20m"),
                    "mode": s.get("mode", "ft8").lower(),
                    **({"dwell_s": int(s["dwell_s"])} if s.get("dwell_s") else {}),
                }
                for s in cfg.get("slots", [])
            ],
        }

    # Stop current rotation if any
    if state.scan_rotation and state.scan_rotation.running:
        await state.scan_rotation.stop()
        state.scan_rotation = None

    # Parse rotation config
    try:
        config = RotationConfig.from_dict(payload)
    except (ValueError, KeyError, TypeError) as exc:
        log(f"preset_scheduler:config_parse_error preset={preset_id} err={exc}")
        return False

    # If no scan running, bootstrap one from the first slot
    if state.scan_state.get("state") != "running":
        first = config.slots[0]
        band_start, band_end = _lookup_band_bounds(first.band)
        if band_start is None or band_end is None:
            return False
        prev_device = (
            state.scan_state.get("device")
            or (state.scan_state.get("scan") or {}).get("device_id")
        )
        # Stop preview if active
        if state.scan_engine.preview:
            await state.scan_engine.stop_async()
        scan_cfg = {
            "band": first.band,
            "start_hz": band_start,
            "end_hz": band_end,
            "center_hz": (band_start + band_end) // 2,
            "step_hz": 2000,
            "dwell_ms": 250,
            "sample_rate": 2048000,
            "mode": "auto",
        }
        if prev_device:
            scan_cfg["device_id"] = prev_device
        try:
            await state.scan_engine.start_async(scan_cfg)
            state.scan_state["state"] = "running"
            state.scan_state["scan"] = scan_cfg
            state.scan_state["started_at"] = datetime.now(timezone.utc).isoformat()
            state.scan_state["scan_id"] = state.db.start_scan(
                scan_cfg, state.scan_state["started_at"],
            )
        except Exception as exc:
            log(f"preset_scheduler:scan_start_error err={exc}")
            return False

    rotation = ScanRotation(config, _rotation_switch_slot)
    state.scan_rotation = rotation
    started = await rotation.start()
    log(f"preset_scheduler:rotation_started preset={preset_id} ok={started}")
    return started


async def _stop_active_rotation() -> None:
    """Stop the current rotation (if any)."""
    if state.scan_rotation and state.scan_rotation.running:
        await state.scan_rotation.stop()


@router.get("/rotation/schedules")
def list_preset_schedules(
    _: bool = Depends(optional_verify_basic_auth),
) -> Dict:
    """List all preset schedules and scheduler status."""
    schedules = state.db.get_preset_schedules()
    sched_status = (
        state.preset_scheduler.status()
        if state.preset_scheduler
        else {"running": False, "active_preset_id": None}
    )
    return {"schedules": schedules, "scheduler": sched_status}


@router.post("/rotation/schedules")
def create_preset_schedule(
    body: Dict,
    _: None = Depends(verify_basic_auth),
) -> Dict:
    """Create a new time-of-day schedule for a rotation preset."""
    preset_id = body.get("preset_id")
    start_hhmm = str(body.get("start_hhmm", "")).strip()
    end_hhmm = str(body.get("end_hhmm", "")).strip()

    if not preset_id or not isinstance(preset_id, int):
        raise HTTPException(status_code=400, detail="preset_id (int) is required")
    if not _HHMM_RE.match(start_hhmm) or not _HHMM_RE.match(end_hhmm):
        raise HTTPException(status_code=400, detail="start_hhmm and end_hhmm must be HH:MM (00:00–23:59)")
    if start_hhmm == end_hhmm:
        raise HTTPException(status_code=400, detail="start and end cannot be the same")

    # Verify preset exists
    presets = state.db.get_rotation_presets()
    if not any(p["id"] == preset_id for p in presets):
        raise HTTPException(status_code=404, detail="Preset not found")

    # Check for overlap with existing enabled schedules
    new_s = _hhmm_to_minutes(start_hhmm)
    new_e = _hhmm_to_minutes(end_hhmm)
    for existing in state.db.get_preset_schedules():
        if not existing.get("enabled"):
            continue
        ex_s = _hhmm_to_minutes(existing["start_hhmm"])
        ex_e = _hhmm_to_minutes(existing["end_hhmm"])
        if _windows_overlap(new_s, new_e, ex_s, ex_e):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Time window {start_hhmm}–{end_hhmm} overlaps with "
                    f"existing schedule \"{existing['preset_name']}\" "
                    f"({existing['start_hhmm']}–{existing['end_hhmm']})"
                ),
            )

    return state.db.save_preset_schedule(preset_id, start_hhmm, end_hhmm)


@router.patch("/rotation/schedules/{schedule_id}")
def toggle_preset_schedule(
    schedule_id: int,
    body: Dict,
    _: None = Depends(verify_basic_auth),
) -> Dict:
    """Enable or disable a preset schedule."""
    enabled = body.get("enabled")
    if enabled is None or not isinstance(enabled, bool):
        raise HTTPException(status_code=400, detail="'enabled' (bool) is required")
    if not state.db.toggle_preset_schedule(schedule_id, enabled):
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"ok": True}


@router.delete("/rotation/schedules/{schedule_id}")
def delete_preset_schedule(
    schedule_id: int,
    _: None = Depends(verify_basic_auth),
) -> Dict:
    """Delete a preset schedule."""
    if not state.db.delete_preset_schedule(schedule_id):
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"ok": True}


@router.post("/rotation/scheduler/start")
async def scheduler_start(
    _: None = Depends(verify_basic_auth),
) -> Dict:
    """Start the preset scheduler (time-of-day auto-switching)."""
    if state.preset_scheduler and state.preset_scheduler.running:
        return {"status": "already_running", **state.preset_scheduler.status()}

    scheduler = PresetScheduler(
        get_schedules=state.db.get_preset_schedules,
        apply_preset_cb=_apply_preset_by_id,
        stop_rotation_cb=_stop_active_rotation,
        is_rotation_running=lambda: bool(state.scan_rotation and state.scan_rotation.running),
    )
    state.preset_scheduler = scheduler
    await scheduler.start()
    log("preset_scheduler_started")
    return scheduler.status()


@router.post("/rotation/scheduler/stop")
async def scheduler_stop(
    _: None = Depends(verify_basic_auth),
) -> Dict:
    """Stop the preset scheduler. Current rotation continues running."""
    if not state.preset_scheduler or not state.preset_scheduler.running:
        raise HTTPException(status_code=400, detail="Scheduler is not running")
    await state.preset_scheduler.stop()
    log("preset_scheduler_stopped")
    return state.preset_scheduler.status()
