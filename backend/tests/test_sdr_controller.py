# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

import app.sdr.controller as controller


class _DummyDevice:
    def __init__(self):
        self.calls = []

    def writeSetting(self, key, value):
        self.calls.append((key, value))


def test_detect_rtl_generation_v3_and_v4():
    assert controller._detect_rtl_generation({
        "driver": "rtlsdr",
        "manufacturer": "RTLSDRBlog",
        "product": "Blog V3",
    }) == 3

    assert controller._detect_rtl_generation({
        "driver": "rtlsdr",
        "manufacturer": "RTLSDRBlog",
        "product": "Blog V4",
    }) == 4


def test_detect_rtl_generation_non_rtlsdr_is_none():
    assert controller._detect_rtl_generation({
        "driver": "audio",
        "product": "Blog V4",
    }) is None


def test_apply_direct_sampling_v3_enables_below_threshold_and_disables_above():
    device = _DummyDevice()
    controller._last_direct_samp_mode = ""

    controller._apply_direct_sampling(device, 7_100_000, rtl_generation=3)
    controller._apply_direct_sampling(device, 28_000_000, rtl_generation=3)

    assert ("direct_samp", "2") in device.calls
    assert ("direct_samp", "0") in device.calls


def test_apply_direct_sampling_v4_forces_disabled_for_hf():
    device = _DummyDevice()
    controller._last_direct_samp_mode = ""

    controller._apply_direct_sampling(device, 7_100_000, rtl_generation=4)

    assert device.calls == [("direct_samp", "0")]


def test_apply_direct_sampling_unknown_keeps_legacy_behavior():
    device = _DummyDevice()
    controller._last_direct_samp_mode = ""

    controller._apply_direct_sampling(device, 7_100_000, rtl_generation=None)

    assert device.calls == [("direct_samp", "2")]


def test_get_rtl_runtime_status_for_v4_policy_and_modes():
    ctrl = controller.SDRController()
    controller._last_rtl_generation = 4
    controller._last_direct_samp_mode = "0"

    status = ctrl.get_rtl_runtime_status(center_hz=7_150_000)

    assert status["rtl_generation_detected"] == 4
    assert status["direct_sampling_policy"] == "force_off_v4_plus"
    assert status["direct_sampling_mode_target"] == "0"
    assert status["direct_sampling_mode_applied"] == "0"


def test_get_rtl_runtime_status_for_v3_hf_target_mode_2():
    ctrl = controller.SDRController()
    controller._last_rtl_generation = 3
    controller._last_direct_samp_mode = "2"

    status = ctrl.get_rtl_runtime_status(center_hz=7_150_000)

    assert status["rtl_generation_detected"] == 3
    assert status["direct_sampling_policy"] == "v3_hf_direct_sampling_below_24mhz"
    assert status["direct_sampling_mode_target"] == "2"


class _CloseRaisesDevice:
    def __init__(self):
        self.calls = []

    def deactivateStream(self, stream):
        self.calls.append(("deactivate", stream))
        raise RuntimeError("deactivate failed")

    def closeStream(self, stream):
        self.calls.append(("close", stream))


def test_close_still_attempts_close_stream_after_deactivate_failure():
    ctrl = controller.SDRController()
    device = _CloseRaisesDevice()

    ctrl.close(device, "stream-1")

    assert device.calls == [
        ("deactivate", "stream-1"),
        ("close", "stream-1"),
    ]
