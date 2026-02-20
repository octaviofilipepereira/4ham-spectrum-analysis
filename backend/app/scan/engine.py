class ScanEngine:
    def __init__(self, controller):
        self.controller = controller
        self.running = False
        self.config = None
        self.device = None
        self.stream = None
        self.sample_rate = 48000
        self.center_hz = 0

    def start(self, config):
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
        return True

    def stop(self):
        self.controller.close(self.device, self.stream)
        self.running = False
        return True

    def read_iq(self, num_samples):
        if not self.running:
            return None
        return self.controller.read_samples(self.device, self.stream, num_samples)
