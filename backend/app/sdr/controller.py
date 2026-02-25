# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 16:27:19 UTC

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


# RTL-SDR V3 direct-sampling threshold: frequencies below this
# value (Hz) require direct sampling mode (Q-branch = 2) for HF.
_DIRECT_SAMPLING_THRESHOLD_HZ = 24_000_000


_last_direct_samp_mode: str = ""


def _apply_direct_sampling(device, center_hz):
    """Enable or disable RTL-SDR V3 direct sampling based on frequency.

    For frequencies below 24 MHz, enables Q-branch direct sampling
    (mode 2) which bypasses the R820T2 tuner and samples the ADC
    directly — required for HF reception on RTL-SDR V3.
    For frequencies >= 24 MHz, disables direct sampling so the
    R820T2 tuner is used normally.

    Caches the last mode to avoid redundant writes (the driver prints
    a log line on every writeSetting call).
    """
    global _last_direct_samp_mode
    try:
        freq = int(center_hz or 0)
        if freq <= 0:
            return
        mode = "2" if freq < _DIRECT_SAMPLING_THRESHOLD_HZ else "0"
        if mode != _last_direct_samp_mode:
            device.writeSetting("direct_samp", mode)
            _last_direct_samp_mode = mode
    except Exception:
        pass


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
        global _last_direct_samp_mode
        # Reset cache: hardware reverts to mode "0" every time the device is
        # closed, so the next open() MUST re-apply the correct mode even when
        # the frequency (and therefore the desired mode) hasn't changed.
        _last_direct_samp_mode = ""
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
            _apply_direct_sampling(device, center_hz)
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
        import logging as _logging
        _log = _logging.getLogger(__name__)

        SoapySDR = _import_soapy_sdr()
        OVERFLOW = getattr(SoapySDR, "SOAPY_SDR_OVERFLOW", -4) if SoapySDR else -4
        TIMEOUT  = getattr(SoapySDR, "SOAPY_SDR_TIMEOUT",   -1) if SoapySDR else -1

        # Use a generous timeout (300 ms) to tolerate USB latency spikes on
        # RTL-SDR devices.  The default of 100 ms triggers spurious TIMEOUT
        # errors under modest CPU load.
        timeout_us = 300_000

        buff = np.empty(num_samples, np.complex64)
        sr = device.readStream(stream, [buff], num_samples, timeoutUs=timeout_us)

        if sr.ret == OVERFLOW:
            # Buffer overflow: host couldn't drain fast enough.  Discard the
            # stale data by performing a non-blocking drain, then do one more
            # real read so the caller gets fresh samples instead of None.
            _log.debug("SoapySDR readStream overflow — draining buffer")
            _drain = np.empty(num_samples * 4, np.complex64)
            device.readStream(stream, [_drain], len(_drain), timeoutUs=0)
            sr = device.readStream(stream, [buff], num_samples, timeoutUs=timeout_us)

        if sr.ret <= 0:
            if sr.ret == TIMEOUT:
                _log.debug("SoapySDR readStream timeout (ret=%d)", sr.ret)
            else:
                _log.debug("SoapySDR readStream error ret=%d", sr.ret)
            return None

        return buff[: sr.ret]

    def tune(self, device, center_hz):
        if device is None or center_hz is None:
            return
        SoapySDR = _import_soapy_sdr()
        if SoapySDR is None:
            return
        SOAPY_SDR_RX = SoapySDR.SOAPY_SDR_RX
        _apply_direct_sampling(device, center_hz)
        device.setFrequency(SOAPY_SDR_RX, 0, int(center_hz))

    def close(self, device, stream):
        if device is None or stream is None:
            return
        try:
            device.deactivateStream(stream)
            device.closeStream(stream)
        except Exception:
            return
