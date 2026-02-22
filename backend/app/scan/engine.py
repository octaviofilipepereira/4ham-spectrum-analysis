# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 16:27:19 UTC

import asyncio


class ScanEngine:
    def __init__(self, controller):
        self.controller = controller
        self.running = False
        self.config = None
        self.device = None
        self.stream = None
        self.sample_rate = 48000
        self.center_hz = 0
        self.mode = "auto"
        self.start_hz = 0
        self.end_hz = 0
        self.step_hz = 0
        self.dwell_ms = 250
        self.settle_ms = 0
        self.current_hz = 0
        self.step_index = 0
        self.total_steps = 0
        self.pass_count = 0
        self._task = None
        self._record_fp = None

    async def start_async(self, config):
        self.config = config or {}
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

    async def stop_async(self):
        self.running = False
        if self._task:
            self._task.cancel()
            self._task = None
        if self._record_fp:
            self._record_fp.close()
            self._record_fp = None
        self.controller.close(self.device, self.stream)
        return True

    async def _scan_loop(self):
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
                self.center_hz = freq
                self.current_hz = freq
                self.controller.tune(self.device, freq)
                if settle_ms > 0:
                    await asyncio.sleep(settle_ms / 1000.0)
                await asyncio.sleep(dwell_ms / 1000.0)
                freq += step_hz
                self.step_index += 1
            self.pass_count += 1

    def read_iq(self, num_samples):
        if not self.running:
            return None
        samples = self.controller.read_samples(self.device, self.stream, num_samples)
        if samples is not None and self._record_fp:
            self._record_fp.write(samples.tobytes())
        return samples

    def status(self):
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
