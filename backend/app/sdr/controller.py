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

    def open(self, device_id=None, sample_rate=48000, center_hz=0, gain=None):
        try:
            import SoapySDR
            from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32
        except Exception:
            return None, None

        device_args = {}
        if device_id:
            for args in SoapySDR.Device.enumerate():
                if args.get("driver") == device_id:
                    device_args = args
                    break

        device = SoapySDR.Device(device_args)
        device.setSampleRate(SOAPY_SDR_RX, 0, sample_rate)
        if center_hz:
            device.setFrequency(SOAPY_SDR_RX, 0, center_hz)
        if gain is not None:
            device.setGain(SOAPY_SDR_RX, 0, gain)

        stream = device.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
        device.activateStream(stream)
        return device, stream

    def read_samples(self, device, stream, num_samples):
        if device is None or stream is None:
            return None

        import numpy as np
        buff = np.empty(num_samples, np.complex64)
        sr = device.readStream(stream, [buff], num_samples)
        if sr.ret <= 0:
            return None
        return buff[: sr.ret]

    def close(self, device, stream):
        if device is None or stream is None:
            return
        try:
            device.deactivateStream(stream)
            device.closeStream(stream)
        except Exception:
            return
