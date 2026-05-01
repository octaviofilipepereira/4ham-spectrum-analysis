# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
NCDXF/IARU Beacon Scheduler — UTC-aligned slot loop.

Operates in two complementary modes (selectable at runtime):

  BAND_SEQUENTIAL (default)
      Stay on one band for a full 3-minute cycle (18 beacons × 10 s).
      Then advance to the next band in the configured list.
      A complete pass over all 5 bands takes ~15 minutes.
      Best for operators who want propagation data on a specific band.

  SLOT_FOLLOW
      Follow the first band of the rotation exactly; at each 10 s boundary
      change to whichever band-0 beacon is transmitting.  With a single SDR
      this is equivalent to BAND_SEQUENTIAL on band 0, but the slot alignment
      is still drawn from UTC so the scheduler stays coherent.

The scheduler does NOT talk to the SDR directly.  It uses the same
scan_park / scan_unpark / iq_provider callbacks as CWSweepDecoder so it
integrates with the existing ScanEngine lifecycle without changes.

Callback contract
-----------------
on_observation(obs: dict)
    Called after each 10 s slot with a filled ObservationResult-like dict.
    Keys: beacon_callsign, beacon_index, band_name, freq_hz, slot_index,
    slot_start_utc, detected, id_confirmed, id_confidence, drift_ms,
    dash_levels_detected, snr_db_100w, snr_db_10w, snr_db_1w, snr_db_100mw.

on_slot_start(beacon_callsign, freq_hz, slot_index, slot_start_utc)
    Called at the START of each slot (before IQ collection).  Used by the
    frontend WebSocket to highlight the active cell in the matrix.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import numpy as np

from .catalog import (
    BANDS,
    BEACONS,
    CYCLE_SECONDS,
    SLOT_SECONDS,
    SLOTS_PER_CYCLE,
    BeaconBand,
    beacon_at,
    current_slot_index,
    next_slot_start,
    seconds_into_slot,
)
from .matched_filter import SlotDetector

_log = logging.getLogger("uvicorn.error")

# Collect IQ for the whole slot minus guard time + settle
_SETTLE_S: float = 0.15     # seconds to discard after park() before collecting
_GUARD_S: float  = 0.30     # seconds of silence at slot end to skip
_COLLECT_S: float = SLOT_SECONDS - _SETTLE_S - _GUARD_S   # ~9.55 s

# Minimum fraction of expected samples to consider a window valid
_MIN_FILL_RATIO: float = 0.6


class BeaconScheduler:
    """UTC-aligned NCDXF beacon slot scheduler.

    Parameters
    ----------
    bands : list[BeaconBand]
        Ordered list of bands to monitor.  Defaults to all five NCDXF bands.
    iq_provider : callable
        No-argument callable returning a complex64 ndarray chunk or None.
    iq_flush : callable
        Callable that drains stale IQ from the SDR queue.
    sample_rate_provider : callable
        Returns current SDR sample rate (Hz).
    scan_park : callable(int)
        Freeze SDR on this centre frequency (Hz).
    scan_unpark : callable
        Resume normal scan engine sweep.
    on_observation : callable(dict)
        Called after each 10 s slot with the observation result.
    on_slot_start : callable(str, int, int, str) | None
        Called at slot start: (callsign, freq_hz, slot_index, slot_start_iso).
    target_sample_rate : int
        Audio sample rate to resample IQ to before detection (default 8000 Hz).
    """

    def __init__(
        self,
        bands: list[BeaconBand] | None = None,
        iq_provider: Optional[Callable[[], Optional[np.ndarray]]] = None,
        iq_flush: Optional[Callable[[], None]] = None,
        sample_rate_provider: Optional[Callable[[], int]] = None,
        scan_park: Optional[Callable[[int], None]] = None,
        scan_unpark: Optional[Callable[[], None]] = None,
        on_observation: Optional[Callable[[dict], None]] = None,
        on_slot_start: Optional[Callable[[str, int, int, str], None]] = None,
        target_sample_rate: int = 8000,
    ) -> None:
        self._bands = list(bands or BANDS)
        self._iq_provider = iq_provider
        self._iq_flush = iq_flush
        self._sample_rate_provider = sample_rate_provider
        self._scan_park = scan_park
        self._scan_unpark = scan_unpark
        self._on_observation = on_observation
        self._on_slot_start = on_slot_start
        self._target_sr = max(4000, int(target_sample_rate))

        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._band_index: int = 0           # current position in self._bands
        self._slots_on_band: int = 0        # slots completed on the current band
        self._total_slots: int = 0
        self._total_observations: int = 0
        self._started_at: Optional[str] = None
        self._stopped_at: Optional[str] = None
        self._last_error: Optional[str] = None

    # ── Public interface ──────────────────────────────────────────────────────

    async def start(self) -> bool:
        """Start the UTC-aligned slot loop.  Returns False if already running."""
        if self._running:
            return False
        self._running = True
        self._started_at = _now_iso()
        self._stopped_at = None
        self._task = asyncio.create_task(self._run())
        _log.info(
            "beacon_scheduler_started bands=%s target_sr=%d",
            [b.name for b in self._bands],
            self._target_sr,
        )
        return True

    async def stop(self) -> bool:
        """Stop the scheduler and release the scan engine park."""
        if not self._running:
            return False
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._release_park()
        self._stopped_at = _now_iso()
        _log.info(
            "beacon_scheduler_stopped total_slots=%d total_observations=%d",
            self._total_slots, self._total_observations,
        )
        return True

    def snapshot(self) -> dict[str, Any]:
        band = self._bands[self._band_index] if self._bands else None
        return {
            "running": self._running,
            "bands": [b.name for b in self._bands],
            "current_band": band.name if band else None,
            "current_freq_hz": band.freq_hz if band else None,
            "slots_on_band": self._slots_on_band,
            "total_slots": self._total_slots,
            "total_observations": self._total_observations,
            "started_at": self._started_at,
            "stopped_at": self._stopped_at,
            "last_error": self._last_error,
        }

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def _run(self) -> None:
        try:
            await self._slot_loop()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._last_error = str(exc)
            _log.exception("beacon_scheduler_error: %s", exc)

    async def _slot_loop(self) -> None:
        """Main UTC-aligned slot loop."""
        # ── 1. Align to the next 10-second UTC boundary ───────────────────────
        now = datetime.now(timezone.utc)
        wait_s = SLOT_SECONDS - (now.timestamp() % SLOT_SECONDS)
        if wait_s < 0.2:
            # Too close to the boundary — skip to the one after
            wait_s += SLOT_SECONDS
        _log.info("beacon_scheduler_aligning wait=%.2fs", wait_s)
        await asyncio.sleep(wait_s)

        # ── 2. Slot loop ──────────────────────────────────────────────────────
        while self._running:
            slot_start_utc = datetime.now(timezone.utc)
            slot_index = current_slot_index(slot_start_utc)
            band = self._bands[self._band_index]

            # Identify expected beacon on this (slot, band)
            beacon = beacon_at(slot_index, band.index)

            # Notify frontend of slot start (for live highlight)
            if self._on_slot_start:
                try:
                    self._on_slot_start(
                        beacon.callsign, band.freq_hz,
                        slot_index, slot_start_utc.isoformat(),
                    )
                except Exception:
                    pass

            # Park SDR on beacon frequency
            if self._scan_park:
                self._scan_park(band.freq_hz)

            # Flush stale IQ then wait for SDR PLL settle
            if self._iq_flush:
                self._iq_flush()
            await asyncio.sleep(_SETTLE_S)

            # Collect IQ for the usable window
            src_sr = self._sample_rate_provider() if self._sample_rate_provider else self._target_sr
            audio = await self._collect_audio(src_sr, slot_start_utc)

            # Slot timing
            self._total_slots += 1
            self._slots_on_band += 1

            # Detect: run matched filter if we got enough audio
            obs: dict[str, Any] = {
                "beacon_callsign": beacon.callsign,
                "beacon_index": beacon.index,
                "beacon_location": beacon.location,
                "beacon_status": beacon.status,
                "band_name": band.name,
                "freq_hz": band.freq_hz,
                "slot_index": slot_index,
                "slot_start_utc": slot_start_utc.isoformat(),
                "detected": False,
                "id_confirmed": False,
                "id_confidence": 0.0,
                "drift_ms": None,
                "dash_levels_detected": 0,
                "snr_db_100w": None,
                "snr_db_10w": None,
                "snr_db_1w": None,
                "snr_db_100mw": None,
            }

            if audio is not None and len(audio) >= int(_MIN_FILL_RATIO * _COLLECT_S * self._target_sr):
                detector = SlotDetector(
                    callsign=beacon.callsign,
                    sample_rate=self._target_sr,
                    slot_start_utc=slot_start_utc,
                )
                result = detector.detect(audio)
                obs.update(result)
                if obs["detected"]:
                    self._total_observations += 1
                _log.info(
                    "beacon_slot beacon=%s band=%s detected=%s id=%s "
                    "dashes=%d snr100w=%s drift_ms=%s",
                    beacon.callsign, band.name, obs["detected"],
                    obs["id_confirmed"], obs["dash_levels_detected"],
                    obs["snr_db_100w"], obs["drift_ms"],
                )
            else:
                _log.debug(
                    "beacon_slot_no_audio beacon=%s band=%s", beacon.callsign, band.name
                )

            # Emit observation
            if self._on_observation:
                try:
                    self._on_observation(obs)
                except Exception:
                    _log.exception("beacon_scheduler on_observation error")

            # Advance band after a full cycle on current band
            if self._slots_on_band >= SLOTS_PER_CYCLE:
                self._slots_on_band = 0
                self._band_index = (self._band_index + 1) % len(self._bands)
                next_band = self._bands[self._band_index]
                _log.info(
                    "beacon_band_advance old=%s next=%s",
                    band.name, next_band.name,
                )

            # Sleep until the next slot boundary
            remaining = SLOT_SECONDS - seconds_into_slot()
            # Clamp: at least 0.1 s, at most 10 s
            remaining = max(0.1, min(float(SLOT_SECONDS), remaining))
            await asyncio.sleep(remaining)

    # ── IQ collection ─────────────────────────────────────────────────────────

    async def _collect_audio(
        self,
        src_sr: int,
        slot_start_utc: datetime,
    ) -> Optional[np.ndarray]:
        """Collect _COLLECT_S seconds of IQ, demodulate (np.real), resample."""
        if not self._iq_provider:
            return None

        target_samples = int(_COLLECT_S * self._target_sr)
        deadline = slot_start_utc.timestamp() + SLOT_SECONDS - _GUARD_S
        buf: list[np.ndarray] = []
        collected = 0

        while collected < target_samples and self._running:
            if datetime.now(timezone.utc).timestamp() >= deadline:
                break
            chunk = self._iq_provider()
            if chunk is None or len(chunk) == 0:
                await asyncio.sleep(0.005)
                continue
            audio = np.real(chunk).astype(np.float32)
            # Resample if necessary
            if src_sr != self._target_sr:
                try:
                    from scipy.signal import resample_poly
                    from math import gcd
                    g = gcd(self._target_sr, src_sr)
                    audio = resample_poly(audio, self._target_sr // g, src_sr // g)
                except Exception:
                    pass
            buf.append(audio)
            collected += len(audio)
            await asyncio.sleep(0)  # yield to event loop

        if not buf:
            return None
        return np.concatenate(buf)[:target_samples]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _release_park(self) -> None:
        if self._scan_unpark:
            try:
                self._scan_unpark()
            except Exception:
                pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
