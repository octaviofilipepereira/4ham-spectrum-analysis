import numpy as np

from app.dsp.pipeline import estimate_occupancy


def test_estimate_occupancy_empty():
    assert estimate_occupancy([], 48000) == []


def test_estimate_occupancy_basic():
    iq = (np.random.randn(4096) + 1j * np.random.randn(4096)) * 0.01
    result = estimate_occupancy(iq, 48000, threshold_dbm=-120.0)
    assert isinstance(result, list)
    assert result[0]["occupied"] in (True, False)
