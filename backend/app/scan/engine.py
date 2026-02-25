# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-24 12:00:00 UTC

import asyncio
import os
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
        if self.step_hz > 0 and self.end_hz > self.start_hz:
            span = self.end_hz - self.start_hz
            self.total_steps = (span // self.step_hz) + 1
        else:
            self.total_steps = 0
        self.step_index = 0
        self.pass_count = 0
        record_path = self.config.get("record_path")
        device_id = self.config.get("device_id")
        self.device, self.stream = self.controller.open(
            device_id=device_id,
            sample_rate=self.sample_rate,
            center_hz=self.center_hz,
            gain=self.config.get("gain")
        )
        if record_path:
            self._record_fp = open(record_path, "wb")
        self.running = True
        if self.mode == "auto" and self.step_hz > 0 and self.end_hz > self.start_hz:
            self._task = asyncio.create_task(self._scan_loop())
        else:
            self.controller.tune(self.device, self.center_hz)
        return True

    async def stop_async(self) -> bool:
        self.running = False
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
        self.device, self.stream = self.controller.open(
            device_id=device_id,
            sample_rate=self.sample_rate,
            center_hz=self.center_hz,
            gain=gain,
        )
        if self.device is None:
            self.preview_start_hz = 0
            self.preview_end_hz = 0
            return False
        self.preview = True
        return True

    def preview_close(self) -> None:
        """Close the preview device session.

        No-op when a scan is running (the scan owns the device).
        """
        if not self.preview or self.running:
            return
        try:
            self.controller.close(self.device, self.stream)
        except Exception:
            pass
        self.device = None
        self.stream = None
        self.preview = False
        self.preview_start_hz = 0
        self.preview_end_hz = 0

    def park(self, frequency_hz: int) -> None:
        """Hold the scanner on *frequency_hz* until unpark() is called.

        The scan loop will stop hopping and stay on this frequency,
        allowing the FT decoder to capture a clean audio window.
        """
        self._parked = True
        self._parked_event.clear()
        self.center_hz = int(frequency_hz)
        self.current_hz = int(frequency_hz)
        self.controller.tune(self.device, int(frequency_hz))

    def unpark(self) -> None:
        """Resume normal scan sweeping."""
        self._parked = False
        self._parked_event.set()

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
                freq += step_hz
                self.step_index += 1
            self.pass_count += 1

    def read_iq(self, num_samples: int) -> Optional[npt.NDArray[np.complex64]]:
        if not self.running and not self.preview:
            return None
        samples = self.controller.read_samples(self.device, self.stream, num_samples)
        if samples is not None and self._record_fp and self.running:
            data = samples.tobytes()
            # Enforce recording size limit
            if self._record_max_bytes > 0 and self._record_bytes + len(data) > self._record_max_bytes:
                # Close and discard the file pointer — recording is full
                try:
                    self._record_fp.close()
                except Exception:
                    pass
                self._record_fp = None
                self._record_bytes = 0
                # Log once so the operator knows recording stopped
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "IQ recording stopped: size limit reached "
                    "(%d MB). Set RECORD_MAX_BYTES=0 to disable limit.",
                    self._record_max_bytes // (1024 * 1024),
                )
            else:
                self._record_fp.write(data)
                self._record_bytes += len(data)
        return samples

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
            "settle_ms": self.settle_ms
        }
