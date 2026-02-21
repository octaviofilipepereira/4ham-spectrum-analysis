import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.dsp.pipeline import classify_mode_heuristic, estimate_occupancy


@dataclass
class IQHarnessResult:
    sample_name: str
    occupancy_count: int
    best_peak_snr_db: float
    mode: str
    mode_confidence: float


def _load_fixture(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_iq_samples(fixture: dict) -> np.ndarray:
    if "iq_pattern" not in fixture:
        raise ValueError("Fixture must include 'iq_pattern'.")

    pattern = np.asarray(fixture["iq_pattern"], dtype=np.float32)
    if pattern.ndim != 2 or pattern.shape[1] != 2:
        raise ValueError("'iq_pattern' must be an array of [i, q] pairs.")

    repeat = int(fixture.get("repeat", 1))
    if repeat < 1:
        raise ValueError("'repeat' must be >= 1.")

    iq_i = np.tile(pattern[:, 0], repeat)
    iq_q = np.tile(pattern[:, 1], repeat)
    noise_std = float(fixture.get("noise_std", 0.0))
    if noise_std > 0:
        iq_i = iq_i + np.random.normal(0.0, noise_std, size=iq_i.shape)
        iq_q = iq_q + np.random.normal(0.0, noise_std, size=iq_q.shape)

    return (iq_i + 1j * iq_q).astype(np.complex64)


def run_iq_fixture(path: Path) -> IQHarnessResult:
    fixture = _load_fixture(path)
    sample_rate = int(fixture["sample_rate"])
    iq_samples = _build_iq_samples(fixture)
    snr_threshold_db = float(fixture.get("snr_threshold_db", 4.0))
    min_bw_hz = int(fixture.get("min_bw_hz", 20))

    occupancy = estimate_occupancy(
        iq_samples,
        sample_rate,
        snr_threshold_db=snr_threshold_db,
        min_bw_hz=min_bw_hz,
    )

    main_bw = occupancy[0]["bandwidth_hz"] if occupancy else None
    mode, confidence = classify_mode_heuristic(main_bw, occupancy[0]["snr_db"] if occupancy else 0.0)

    best_peak = 0.0
    if occupancy:
        best_peak = max(float(item.get("snr_db", 0.0)) for item in occupancy)

    result = IQHarnessResult(
        sample_name=fixture.get("name", path.stem),
        occupancy_count=len(occupancy),
        best_peak_snr_db=float(best_peak),
        mode=mode,
        mode_confidence=float(confidence),
    )

    expected = fixture.get("expect", {})
    min_occupancy = int(expected.get("min_occupied_segments", 0))
    if result.occupancy_count < min_occupancy:
        raise AssertionError(
            f"Expected at least {min_occupancy} occupied segments for {result.sample_name}, "
            f"got {result.occupancy_count}."
        )

    min_peak = float(expected.get("min_peak_snr_db", -999.0))
    if result.best_peak_snr_db < min_peak:
        raise AssertionError(
            f"Expected peak SNR >= {min_peak} dB for {result.sample_name}, "
            f"got {result.best_peak_snr_db:.2f} dB."
        )

    expected_mode = expected.get("mode")
    if expected_mode and result.mode != expected_mode:
        raise AssertionError(
            f"Expected mode '{expected_mode}' for {result.sample_name}, got '{result.mode}'."
        )

    return result
