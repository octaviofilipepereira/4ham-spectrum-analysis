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
