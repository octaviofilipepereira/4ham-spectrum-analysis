import numpy as np

from app.dsp.pipeline import estimate_occupancy, apply_agc_smoothed


def test_estimate_occupancy_empty():
    assert estimate_occupancy([], 48000) == []


def test_estimate_occupancy_basic():
    iq = (np.random.randn(4096) + 1j * np.random.randn(4096)) * 0.01
    result = estimate_occupancy(iq, 48000, threshold_dbm=-120.0)
    assert isinstance(result, list)
    assert result[0]["occupied"] in (True, False)


def test_apply_agc_smoothed():
    iq = (np.random.randn(2048) + 1j * np.random.randn(2048)) * 0.02
    state = {}
    scaled, gain_db = apply_agc_smoothed(iq, state, target_rms=0.3, max_gain_db=10.0, alpha=0.5)
    assert scaled is not None
    assert isinstance(gain_db, float)
    assert "gain_db" in state
