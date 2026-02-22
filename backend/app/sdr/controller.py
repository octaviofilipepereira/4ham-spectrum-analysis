import importlib
import sys


def _import_soapy_sdr():
    try:
        return importlib.import_module("SoapySDR")
    except Exception:
        pass

    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    candidate_paths = [
        "/usr/lib/python3/dist-packages",
        "/usr/local/lib/python3/dist-packages",
        f"/usr/lib/python{version}/dist-packages",
        f"/usr/local/lib/python{version}/dist-packages",
    ]
    for path in candidate_paths:
        if path not in sys.path:
            sys.path.append(path)
    try:
        return importlib.import_module("SoapySDR")
    except Exception:
        return None


def soapy_import_status():
    try:
        module = _import_soapy_sdr()
        if module is None:
            return False, "No module named 'SoapySDR'"
        return True, None
    except Exception as exc:
        return False, str(exc)


def _kwargs_to_dict(args):
    if isinstance(args, dict):
        return args
    try:
        return dict(args)
    except Exception:
        return {}


class SDRController:
    def list_devices(self):
        SoapySDR = _import_soapy_sdr()
        if SoapySDR is None:
            return []

        devices = []
        for args in SoapySDR.Device.enumerate():
            details = _kwargs_to_dict(args)
            devices.append({
                "id": details.get("driver", "unknown"),
                "type": details.get("driver", "unknown"),
                "name": details.get("label", details.get("driver", "unknown")),
                "capabilities": ["rx"]
            })
        return devices

    def open(self, device_id=None, sample_rate=48000, center_hz=0, gain=None):
        SoapySDR = _import_soapy_sdr()
        if SoapySDR is None:
            return None, None
        try:
            SOAPY_SDR_RX = SoapySDR.SOAPY_SDR_RX
            SOAPY_SDR_CF32 = SoapySDR.SOAPY_SDR_CF32
        except Exception:
            return None, None

        device_args = {}
        if device_id:
            for args in SoapySDR.Device.enumerate():
                details = _kwargs_to_dict(args)
                if details.get("driver") == device_id:
                    device_args = details
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

    def tune(self, device, center_hz):
        if device is None or center_hz is None:
            return
        SoapySDR = _import_soapy_sdr()
        if SoapySDR is None:
            return
        SOAPY_SDR_RX = SoapySDR.SOAPY_SDR_RX
        device.setFrequency(SOAPY_SDR_RX, 0, int(center_hz))

    def close(self, device, stream):
        if device is None or stream is None:
            return
        try:
            device.deactivateStream(stream)
            device.closeStream(stream)
        except Exception:
            return
