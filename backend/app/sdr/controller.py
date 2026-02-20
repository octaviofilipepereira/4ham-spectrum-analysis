class SDRController:
    def list_devices(self):
        try:
            import SoapySDR
        except Exception:
            return []

        devices = []
        for args in SoapySDR.Device.enumerate():
            devices.append({
                "id": args.get("driver", "unknown"),
                "type": args.get("driver", "unknown"),
                "name": args.get("label", args.get("driver", "unknown")),
                "capabilities": ["rx"]
            })
        return devices

    def open(self, device_id):
        _ = device_id
        return None
