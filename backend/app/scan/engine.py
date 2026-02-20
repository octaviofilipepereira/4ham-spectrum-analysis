class ScanEngine:
    def __init__(self, controller):
        self.controller = controller
        self.running = False
        self.config = None

    def start(self, config):
        self.config = config
        self.running = True
        return True

    def stop(self):
        self.running = False
        return True
