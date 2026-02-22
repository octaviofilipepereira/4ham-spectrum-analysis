# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 16:27:19 UTC

import numpy as np

from app.dsp.pipeline import (
    apply_agc_smoothed,
    classify_mode_heuristic,
    detect_peaks,
    estimate_noise_floor,
    estimate_occupancy,
)


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


def test_detect_peaks_and_noise_floor():
    fft_db = [-40.0, -38.0, -10.0, -38.0, -39.0, -12.0, -39.0]
    noise_floor = estimate_noise_floor(fft_db, percentile=20)
    peaks = detect_peaks(fft_db, bin_hz=100.0, min_snr_db=6.0, max_peaks=3)

    assert noise_floor is not None
    assert noise_floor < -20.0
    assert len(peaks) >= 1
    assert any(item["snr_db"] > 10.0 for item in peaks)


def test_classify_mode_heuristic_bandwidth_ranges():
    mode_cw, conf_cw = classify_mode_heuristic(250, snr_db=12.0)
    mode_ssb, conf_ssb = classify_mode_heuristic(2600, snr_db=12.0)
    mode_fm, conf_fm = classify_mode_heuristic(12500, snr_db=12.0)

    assert mode_cw == "CW"
    assert mode_ssb == "SSB"
    assert mode_fm == "FM"
    assert 0.0 < conf_cw <= 0.95
    assert 0.0 < conf_ssb <= 0.95
    assert 0.0 < conf_fm <= 0.95
