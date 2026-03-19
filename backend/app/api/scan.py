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
from app.api.decoders import (
    _start_cw_decoder,
    _stop_cw_decoder,
    _start_ft_external_decoder,
    _stop_ft_external_decoder,
    _start_ssb_detector,
    _stop_ssb_detector,
)


router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


_CW_SUBBANDS_HZ = {
    "160m": (1_800_000, 1_840_000),
    "80m": (3_500_000, 3_600_000),
    "40m": (7_000_000, 7_040_000),
    "30m": (10_100_000, 10_130_000),
    "20m": (14_000_000, 14_070_000),
    "17m": (18_068_000, 18_110_000),
    "15m": (21_000_000, 21_150_000),
    "12m": (24_890_000, 24_930_000),
    "10m": (28_000_000, 28_300_000),
}

_SSB_SUBBANDS_HZ = {
    "160m": (1_843_000, 2_000_000),
    "80m": (3_600_000, 4_000_000),
    "40m": (7_090_000, 7_200_000),
    "20m": (14_100_000, 14_350_000),
    "17m": (18_100_000, 18_168_000),
    "15m": (21_200_000, 21_450_000),
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
            if state.ft_external_decoder is not None:
                state.ft_external_decoder.set_modes([decoder_mode_upper])
            else:
                result = await _start_ft_external_decoder(force=True)
                log(f"scan_ft_external_decoder_started:{result}")
                if state.ft_external_decoder:
                    state.ft_external_decoder.set_modes([decoder_mode_upper])
            state.ft_external_modes[:] = [decoder_mode_upper]
        else:
            # Other modes (SSB, APRS): stop FT/CW and start SSB detector for SSB
            if state.cw_decoder is not None:
                await _stop_cw_decoder()
            if state.ft_external_decoder is not None:
                await _stop_ft_external_decoder()
            if decoder_mode == "ssb":
                result = await _start_ssb_detector(force=True)
                log(f"scan_ssb_detector_started:{result}")
            else:
                await _stop_ssb_detector()

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
    state.scan_state["state"] = "stopped"
    state.scan_state["decoder_mode"] = ""  # clear so frontend doesn't auto-select the button
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
        # FT8/FT4/WSPR mode: need FT external decoder, stop CW decoder
        
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
        # CW mode: need CW decoder, stop FT external decoder
        
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
        # SSB/APRS mode: stop FT/CW decoders; start SSB detector for SSB
        
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
        else:
            try:
                await _stop_ssb_detector()
            except Exception as exc:
                log(f"scan_ssb_detector_stop_failed:{exc}")

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
