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
        self._task = None

    async def start_async(self, config):
        self.config = config or {}
        self.sample_rate = int(self.config.get("sample_rate", 48000))
        self.center_hz = int(self.config.get("center_hz", self.config.get("start_hz", 0)))
        device_id = self.config.get("device_id")
        self.device, self.stream = self.controller.open(
            device_id=device_id,
            sample_rate=self.sample_rate,
            center_hz=self.center_hz,
            gain=self.config.get("gain")
        )
        self.running = True
        self._task = asyncio.create_task(self._scan_loop())
        return True

    async def stop_async(self):
        self.running = False
        if self._task:
            self._task.cancel()
            self._task = None
        self.controller.close(self.device, self.stream)
        return True

    async def _scan_loop(self):
        start_hz = int(self.config.get("start_hz", self.center_hz))
        end_hz = int(self.config.get("end_hz", start_hz))
        step_hz = int(self.config.get("step_hz", 0))
        dwell_ms = int(self.config.get("dwell_ms", 250))

        if step_hz <= 0 or end_hz <= start_hz:
            return

        while self.running:
            freq = start_hz
            while freq <= end_hz and self.running:
                self.center_hz = freq
                self.controller.tune(self.device, freq)
                await asyncio.sleep(dwell_ms / 1000.0)
                freq += step_hz

    def read_iq(self, num_samples):
        if not self.running:
            return None
        return self.controller.read_samples(self.device, self.stream, num_samples)
