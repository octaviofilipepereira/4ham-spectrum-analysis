class ScanEngine:
    def __init__(self, controller):
        self.controller = controller

    def start(self, config):
        _ = config
        return True

    def stop(self):
        return True
