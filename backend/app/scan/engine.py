# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-24 12:00:00 UTC

import asyncio
import os
import time
from typing import Optional, Dict, Any, BinaryIO
import numpy as np
import numpy.typing as npt

# Default IQ recording size limit: 512 MB.
# Prevents unbounded disk growth at 16 MB/s (2048 kHz × 8 bytes/sample).
# Override via RECORD_MAX_BYTES in .env (0 = no limit).
_DEFAULT_RECORD_MAX_BYTES = 512 * 1024 * 1024


class ScanEngine:
    def __init__(self, controller: Any) -> None:
        self.controller = controller
        self.running: bool = False
        self.config: Optional[Dict[str, Any]] = None
        self.device: Optional[Any] = None
        self.stream: Optional[Any] = None
        self.sample_rate: int = 48000
        self.center_hz: int = 0
        self.mode: str = "auto"
        self.start_hz: int = 0
        self.end_hz: int = 0
        self.step_hz: int = 0
        self.dwell_ms: int = 250
        self.settle_ms: int = 0
        self.current_hz: int = 0
        self.step_index: int = 0
        self.total_steps: int = 0
        self.pass_count: int = 0
        self.preview: bool = False  # True when device open for passive monitoring
        self.preview_start_hz: int = 0  # Band start Hz used during preview (0 = unknown)
        self.preview_end_hz: int = 0    # Band end Hz used during preview (0 = unknown)
        self._task: Optional[asyncio.Task] = None
        self._record_fp: Optional[BinaryIO] = None
        self._record_bytes: int = 0
        # Maximum bytes to write to the IQ recording file (0 = unlimited).
        # Read from RECORD_MAX_BYTES env var; can be overridden per-config.
        try:
            self._record_max_bytes: int = int(
                os.getenv("RECORD_MAX_BYTES", str(_DEFAULT_RECORD_MAX_BYTES))
            )
        except (ValueError, TypeError):
            self._record_max_bytes = _DEFAULT_RECORD_MAX_BYTES
        # Park/hold: when True the scan loop freezes on the current
        # frequency so the FT decoder can capture a clean window.
        self._parked = False
        self._parked_event = asyncio.Event()
        self._parked_event.set()  # Initially not parked
        # IQ fan-out pump — single hardware reader, multiple consumers.
        # _spectrum_queue feeds spectrum.py (FFT), _iq_listeners feeds decoders.
        self._spectrum_queue: Optional[asyncio.Queue] = None
        self._iq_listeners: list = []
        self._pump_task: Optional[asyncio.Task] = None
        # SSB candidate focus mode: keep scan dwell short globally, but extend
        # dwell on frequencies repeatedly flagged as active SSB traffic.
        self._ssb_focus_enabled: bool = False
        self._ssb_focus_hold_ms: int = 15000
        self._ssb_focus_candidate_ttl_s: float = 20.0
        self._ssb_focus_hits_required: int = 2
        self._ssb_focus_cooldown_s: float = 20.0
        self._ssb_focus_bucket_hz: int = 2000
        self._ssb_focus_max_holds_per_pass: int = 4
        self._ssb_focus_holds_in_pass: int = 0
        # bucket_hz -> {hits, last_seen, last_hold_at, max_snr_db, max_confidence}
        self._ssb_focus_candidates: Dict[int, Dict[str, float]] = {}
        # bucket_hz -> timestamp when the frequency was hold-validated
        self._ssb_validated_freqs: Dict[int, float] = {}

    async def start_async(self, config: Optional[Dict[str, Any]]) -> bool:
        self.config = config or {}
        # Allow per-scan override of the recording size limit
        if "record_max_bytes" in self.config:
            try:
                self._record_max_bytes = int(self.config["record_max_bytes"])
            except (ValueError, TypeError):
                pass
        self._record_bytes = 0
        self.sample_rate = int(self.config.get("sample_rate", 48000))
        self.start_hz = int(self.config.get("start_hz", 0))
        self.end_hz = int(self.config.get("end_hz", 0))
        self.step_hz = int(self.config.get("step_hz", 0))
        self.dwell_ms = int(self.config.get("dwell_ms", 250))
        self.settle_ms = int(self.config.get("settle_ms", 0))
        self.mode = self.config.get("mode", "auto")
        self.center_hz = int(self.config.get("center_hz", self.start_hz or 0))
        self.current_hz = self.center_hz
        self._ssb_focus_enabled = bool(self.config.get("ssb_focus_enable", False))
        self._ssb_focus_hold_ms = max(
            int(self.config.get("ssb_focus_hold_ms", 15000) or 15000),
            0,
        )
        self._ssb_focus_candidate_ttl_s = max(
            float(self.config.get("ssb_focus_candidate_ttl_s", 20.0) or 20.0),
            1.0,
        )
        self._ssb_focus_hits_required = max(
            int(self.config.get("ssb_focus_hits_required", 2) or 2),
            1,
        )
        self._ssb_focus_cooldown_s = max(
            float(self.config.get("ssb_focus_cooldown_s", 20.0) or 20.0),
            0.0,
        )
        self._ssb_focus_bucket_hz = max(
            int(self.config.get("ssb_focus_bucket_hz", self.step_hz or 2000) or (self.step_hz or 2000)),
            250,
        )
        self._ssb_focus_max_holds_per_pass = max(
            int(self.config.get("ssb_focus_max_holds_per_pass", 4) or 4),
            1,
        )
        self._ssb_focus_holds_in_pass = 0
        self._ssb_focus_candidates.clear()
        self._ssb_validated_freqs.clear()
        # Always reset parked state on new scan — a previous scan may have left
        # the engine parked (e.g. WSPR window was in progress when scan stopped),
        # which would block the new scan loop immediately.
        self._parked = False
        self._parked_event.set()
        if self.step_hz > 0 and self.end_hz > self.start_hz:
            span = self.end_hz - self.start_hz
            self.total_steps = (span // self.step_hz) + 1
        else:
            self.total_steps = 0
        self.step_index = 0
        self.pass_count = 0
        record_path = self.config.get("record_path")
        device_id = self.config.get("device_id")
        _gain = self.config.get("gain")
        _sr = self.sample_rate
        _chz = self.center_hz
        loop = asyncio.get_event_loop()
        self.device, self.stream = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: self.controller.open(
                    device_id=device_id,
                    sample_rate=_sr,
                    center_hz=_chz,
                    gain=_gain,
                ),
            ),
            timeout=10.0,  # prevent blocking the event loop on USB hang
        )
        if record_path:
            self._record_fp = open(record_path, "wb")
        self.running = True
        self._spectrum_queue = asyncio.Queue(maxsize=8)
        self._pump_task = asyncio.create_task(self._iq_pump_loop())
        if self.mode == "auto" and self.step_hz > 0 and self.end_hz > self.start_hz:
            self._task = asyncio.create_task(self._scan_loop())
        else:
            self.controller.tune(self.device, self.center_hz)
        return True

    async def stop_async(self) -> bool:
        self.running = False
        if self._pump_task:
            self._pump_task.cancel()
            try:
                await self._pump_task
            except asyncio.CancelledError:
                pass
            self._pump_task = None
        self._spectrum_queue = None
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._record_fp:
            try:
                self._record_fp.close()
            except Exception:
                pass
            finally:
                self._record_fp = None
        try:
            self.controller.close(self.device, self.stream)
        except Exception:
            pass
        self.device = None
        self.stream = None
        self.preview = False
        return True

    async def preview_open(
        self,
        device_id: Optional[str] = None,
        sample_rate: int = 2048000,
        center_hz: int = 14175000,
        gain: Optional[float] = None,
        start_hz: int = 0,
        end_hz: int = 0,
    ) -> bool:
        """Open device for passive spectrum monitoring without starting a scan.

        Only effective when no scan is running. Replaces an existing preview
        session if one is already open.

        Args:
            start_hz: Optional band start frequency (Hz). When provided the
                WebSocket frames will carry this as scan_start_hz so the
                frontend ruler matches scan mode exactly.
            end_hz: Optional band end frequency (Hz). Same purpose.
        """
        if self.running:
            return False  # scan owns the device — do not interfere
        # Close existing preview device if open
        if self.preview:
            try:
                self.controller.close(self.device, self.stream)
            except Exception:
                pass
            self.device = None
            self.stream = None
            self.preview = False
        self.sample_rate = int(sample_rate or 2048000)
        self.center_hz = int(center_hz or 14175000)
        self.preview_start_hz = int(start_hz or 0)
        self.preview_end_hz = int(end_hz or 0)
        _sr = self.sample_rate
        _chz = self.center_hz
        loop = asyncio.get_event_loop()
        self.device, self.stream = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: self.controller.open(
                    device_id=device_id,
                    sample_rate=_sr,
                    center_hz=_chz,
                    gain=gain,
                ),
            ),
            timeout=10.0,  # prevent blocking the event loop on USB hang
        )
        if self.device is None:
            self.preview_start_hz = 0
            self.preview_end_hz = 0
            return False
        self.preview = True
        self._spectrum_queue = asyncio.Queue(maxsize=8)
        self._pump_task = asyncio.create_task(self._iq_pump_loop())
        return True

    def preview_close(self) -> None:
        """Close the preview device session.

        No-op when a scan is running (the scan owns the device).
        """
        if not self.preview or self.running:
            return
        if self._pump_task:
            self._pump_task.cancel()
            self._pump_task = None
        self._spectrum_queue = None
        self.preview = False  # clear flag BEFORE closing device
        try:
            self.controller.close(self.device, self.stream)
        except Exception:
            pass
        self.device = None
        self.stream = None
        self.preview_start_hz = 0
        self.preview_end_hz = 0

    def park(self, frequency_hz: int) -> None:
        """Hold the scanner on *frequency_hz* until unpark() is called.

        The scan loop will stop hopping and stay on this frequency,
        allowing the FT decoder to capture a clean audio window.
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"scan_engine_park freq_hz={frequency_hz} device={self.device is not None}")
        self._parked = True
        self._parked_event.clear()
        self.center_hz = int(frequency_hz)
        self.current_hz = int(frequency_hz)
        try:
            self.controller.tune(self.device, int(frequency_hz))
            logger.info(f"scan_engine_parked freq_hz={frequency_hz}")
        except Exception as e:
            logger.error(f"scan_engine_park_tune_error freq_hz={frequency_hz} error={e}")

    def unpark(self) -> None:
        """Resume normal scan sweeping."""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"scan_engine_unpark _parked={self._parked}")
        self._parked = False
        self._parked_event.set()
        logger.info(f"scan_engine_unparked")

    def report_ssb_candidate(
        self,
        frequency_hz: int,
        snr_db: float = 0.0,
        confidence: float = 0.0,
    ) -> None:
        """Report a detected SSB candidate frequency to the scan engine."""
        if not self._ssb_focus_enabled:
            return
        try:
            frequency_hz = int(frequency_hz)
        except (TypeError, ValueError):
            return
        if frequency_hz <= 0:
            return

        now_ts = time.time()
        bucket_hz = max(250, int(self._ssb_focus_bucket_hz or self.step_hz or 2000))
        bucket_key = int(round(frequency_hz / bucket_hz) * bucket_hz)

        stale_before = now_ts - float(self._ssb_focus_candidate_ttl_s)
        for key, candidate in list(self._ssb_focus_candidates.items()):
            if float(candidate.get("last_seen", 0.0)) < stale_before:
                self._ssb_focus_candidates.pop(key, None)

        candidate = self._ssb_focus_candidates.get(bucket_key)
        if candidate is None:
            self._ssb_focus_candidates[bucket_key] = {
                "hits": 1.0,
                "last_seen": now_ts,
                "last_hold_at": 0.0,
                "max_snr_db": float(snr_db or 0.0),
                "max_confidence": float(confidence or 0.0),
            }
            return

        candidate["hits"] = min(float(candidate.get("hits", 0.0)) + 1.0, 1000.0)
        candidate["last_seen"] = now_ts
        candidate["max_snr_db"] = max(float(candidate.get("max_snr_db", 0.0)), float(snr_db or 0.0))
        candidate["max_confidence"] = max(
            float(candidate.get("max_confidence", 0.0)),
            float(confidence or 0.0),
        )

    def _resolve_ssb_focus_extra_dwell_ms(self, frequency_hz: int) -> int:
        if not self._ssb_focus_enabled:
            return 0
        if self._ssb_focus_holds_in_pass >= self._ssb_focus_max_holds_per_pass:
            return 0
        if frequency_hz <= 0:
            return 0

        now_ts = time.time()
        bucket_hz = max(250, int(self._ssb_focus_bucket_hz or self.step_hz or 2000))
        bucket_key = int(round(frequency_hz / bucket_hz) * bucket_hz)
        candidate = self._ssb_focus_candidates.get(bucket_key)
        if candidate is None:
            return 0

        last_seen = float(candidate.get("last_seen", 0.0))
        if (now_ts - last_seen) > float(self._ssb_focus_candidate_ttl_s):
            self._ssb_focus_candidates.pop(bucket_key, None)
            return 0

        hits = int(candidate.get("hits", 0.0) or 0)
        if hits < self._ssb_focus_hits_required:
            return 0

        last_hold_at = float(candidate.get("last_hold_at", 0.0) or 0.0)
        if (now_ts - last_hold_at) < float(self._ssb_focus_cooldown_s):
            return 0

        target_hold_ms = max(int(self._ssb_focus_hold_ms), int(self.dwell_ms))
        extra_ms = max(0, target_hold_ms - int(self.dwell_ms))
        if extra_ms <= 0:
            return 0

        candidate["last_hold_at"] = now_ts
        candidate["hits"] = 0.0
        self._ssb_focus_holds_in_pass += 1
        return extra_ms

    def is_ssb_frequency_validated(self, frequency_hz: int, max_age_s: float = 60.0) -> bool:
        """Check if a frequency has been validated by the SSB focus hold."""
        if not self._ssb_focus_enabled:
            return False
        try:
            frequency_hz = int(frequency_hz)
        except (TypeError, ValueError):
            return False
        if frequency_hz <= 0:
            return False
        bucket_hz = max(250, int(self._ssb_focus_bucket_hz or self.step_hz or 2000))
        bucket_key = int(round(frequency_hz / bucket_hz) * bucket_hz)
        validated_at = self._ssb_validated_freqs.get(bucket_key)
        if validated_at is None:
            return False
        now_ts = time.time()
        if (now_ts - validated_at) > max_age_s:
            self._ssb_validated_freqs.pop(bucket_key, None)
            return False
        return True

    async def _scan_loop(self) -> None:
        start_hz = self.start_hz or self.center_hz
        end_hz = self.end_hz or start_hz
        step_hz = self.step_hz
        dwell_ms = self.dwell_ms
        settle_ms = self.settle_ms

        if step_hz <= 0 or end_hz <= start_hz:
            return

        while self.running:
            freq = start_hz
            self.step_index = 0
            self._ssb_focus_holds_in_pass = 0
            while freq <= end_hz and self.running:
                # If parked by the FT decoder, wait until unparked
                if self._parked:
                    await self._parked_event.wait()
                    if not self.running:
                        break
                    continue
                self.center_hz = freq
                self.current_hz = freq
                self.controller.tune(self.device, freq)
                if settle_ms > 0:
                    await asyncio.sleep(settle_ms / 1000.0)
                await asyncio.sleep(dwell_ms / 1000.0)
                extra_dwell_ms = self._resolve_ssb_focus_extra_dwell_ms(freq)
                if extra_dwell_ms > 0:
                    # Mark validated at hold START so the WS occupancy handler can
                    # emit callsign events throughout the full hold window (not just
                    # the final 1.5 s).
                    bucket_hz = max(250, int(self._ssb_focus_bucket_hz or self.step_hz or 2000))
                    bucket_key = int(round(freq / bucket_hz) * bucket_hz)
                    self._ssb_validated_freqs[bucket_key] = time.time()
                    await asyncio.sleep(extra_dwell_ms / 1000.0)
                freq += step_hz
                self.step_index += 1
            self.pass_count += 1

    def register_iq_listener(self, queue: asyncio.Queue) -> None:
        """Register a decoder queue to receive IQ sample chunks from the pump."""
        if queue not in self._iq_listeners:
            self._iq_listeners.append(queue)

    def unregister_iq_listener(self, queue: asyncio.Queue) -> None:
        """Remove a previously registered decoder queue."""
        try:
            self._iq_listeners.remove(queue)
        except ValueError:
            pass

    def read_iq(self, num_samples: int) -> Optional[npt.NDArray[np.complex64]]:
        """Non-blocking read from the spectrum queue (fed by _iq_pump_loop).

        Returns None immediately when no chunk is available — the caller
        (spectrum.py) is expected to yield and retry.
        """
        if self._spectrum_queue is None:
            return None
        try:
            return self._spectrum_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def _iq_pump_loop(self) -> None:
        """Single hardware reader that fans IQ chunks out to all consumers.

        Reads 4096-sample chunks from the SDR and distributes them to:
        - _spectrum_queue  → spectrum.py FFT loop
        - each queue in _iq_listeners → FT / other decoders

        Both destinations use put_nowait so a slow consumer never blocks
        the hardware read or the other consumer.
        """
        import logging as _logging
        _log = _logging.getLogger(__name__)
        chunk_size = 4096
        while self.running or self.preview:
            try:
                samples = self.controller.read_samples(
                    self.device, self.stream, chunk_size
                )
            except Exception as exc:
                _log.debug("IQ pump read error: %s", exc)
                await asyncio.sleep(0.01)
                continue

            if samples is None:
                await asyncio.sleep(0.005)
                continue

            # Recording (scan mode only)
            if self._record_fp and self.running:
                data = samples.tobytes()
                if self._record_max_bytes > 0 and self._record_bytes + len(data) > self._record_max_bytes:
                    try:
                        self._record_fp.close()
                    except Exception:
                        pass
                    self._record_fp = None
                    self._record_bytes = 0
                    _log.warning(
                        "IQ recording stopped: size limit reached "
                        "(%d MB). Set RECORD_MAX_BYTES=0 to disable limit.",
                        self._record_max_bytes // (1024 * 1024),
                    )
                else:
                    self._record_fp.write(data)
                    self._record_bytes += len(data)

            # Fan-out: spectrum queue (drop oldest if full — FFT can skip)
            if self._spectrum_queue is not None:
                try:
                    self._spectrum_queue.put_nowait(samples)
                except asyncio.QueueFull:
                    try:
                        self._spectrum_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    try:
                        self._spectrum_queue.put_nowait(samples)
                    except asyncio.QueueFull:
                        pass

            # Fan-out: each registered decoder listener (copy per consumer)
            for q in list(self._iq_listeners):
                chunk_copy = samples.copy()
                try:
                    q.put_nowait(chunk_copy)
                except asyncio.QueueFull:
                    pass  # decoder is too slow — drop; it will flush stale IQ

            await asyncio.sleep(0)

    def status(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "current_hz": self.current_hz,
            "step_index": self.step_index,
            "total_steps": self.total_steps,
            "pass_count": self.pass_count,
            "sample_rate": self.sample_rate,
            "start_hz": self.start_hz,
            "end_hz": self.end_hz,
            "step_hz": self.step_hz,
            "dwell_ms": self.dwell_ms,
            "settle_ms": self.settle_ms,
            "ssb_focus_enable": self._ssb_focus_enabled,
            "ssb_focus_hold_ms": self._ssb_focus_hold_ms,
            "ssb_focus_hits_required": self._ssb_focus_hits_required,
            "ssb_focus_candidate_ttl_s": self._ssb_focus_candidate_ttl_s,
            "ssb_focus_cooldown_s": self._ssb_focus_cooldown_s,
            "ssb_focus_bucket_hz": self._ssb_focus_bucket_hz,
            "ssb_focus_max_holds_per_pass": self._ssb_focus_max_holds_per_pass,
            "ssb_focus_candidates": len(self._ssb_focus_candidates),
            "ssb_focus_holds_in_pass": self._ssb_focus_holds_in_pass,
        }
