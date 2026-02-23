# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 18:20:00 UTC

from app.decoders.ft_pipeline import detect_ft8_candidates, detect_ft_candidates


def test_detect_ft8_candidates_filters_by_audio_window_and_snr():
    snapshot = {
        "center_hz": 14074000,
        "bin_hz": 10.0,
        "noise_floor_db": -120.0,
        "peaks": [
            {"offset_hz": 120.0, "db": -90.0},
            {"offset_hz": 350.0, "db": -111.0},
            {"offset_hz": 950.0, "db": -94.0},
            {"offset_hz": 3800.0, "db": -85.0},
        ],
    }

    candidates = detect_ft8_candidates(snapshot, min_snr_db=10.0)

    assert len(candidates) == 1
    assert candidates[0]["mode"] == "FT8"
    assert candidates[0]["frequency_hz"] == 14074950
    assert candidates[0]["snr_db"] > 10.0


def test_detect_ft8_candidates_uses_fft_when_peaks_missing():
    fft_db = [-130.0] * 64
    fft_db[32 + 20] = -95.0
    snapshot = {
        "center_hz": 7074000,
        "bin_hz": 10.0,
        "noise_floor_db": -120.0,
        "peaks": [],
        "fft_db": fft_db,
    }

    candidates = detect_ft8_candidates(snapshot, min_snr_db=12.0)

    assert len(candidates) >= 1
    first = candidates[0]
    assert first["mode"] == "FT8"
    assert first["frequency_hz"] == 7074200
    assert first["confidence"] > 0.5


def test_detect_ft_candidates_hints_mode_by_band_frequency():
    snapshot = {
        "center_hz": 14074000,
        "noise_floor_db": -120.0,
        "peaks": [
            {"offset_hz": 350.0, "db": -94.0},
            {"offset_hz": 6000.0, "db": -90.0},
        ],
    }

    candidates = detect_ft_candidates(
        snapshot,
        min_snr_db=10.0,
        min_audio_hz=150.0,
        max_audio_hz=7000.0,
        modes=["FT8", "FT4"],
    )

    assert len(candidates) == 2
    modes = {item["frequency_hz"]: item["mode"] for item in candidates}
    assert modes[14074350] == "FT8"
    assert modes[14080000] == "FT4"
