# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 00:34:50 UTC

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.dsp.pipeline import detect_peaks, estimate_occupancy, compute_fft_db


def _generate_iq(size: int, sample_rate: int) -> np.ndarray:
    t = np.arange(size, dtype=np.float32) / float(sample_rate)
    tone_1 = np.exp(1j * 2.0 * np.pi * 700.0 * t)
    tone_2 = 0.6 * np.exp(1j * 2.0 * np.pi * 1700.0 * t)
    noise = (np.random.randn(size) + 1j * np.random.randn(size)) * 0.08
    return (tone_1 + tone_2 + noise).astype(np.complex64)


def _time_call(fn, iterations: int):
    samples = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        samples.append(elapsed_ms)
    return {
        "iterations": iterations,
        "min_ms": float(min(samples)),
        "max_ms": float(max(samples)),
        "mean_ms": float(statistics.mean(samples)),
        "p95_ms": float(np.percentile(samples, 95)),
    }


def run_benchmark(sample_rate: int, fft_size: int, iterations: int) -> dict:
    iq = _generate_iq(fft_size, sample_rate)

    def bench_fft():
        compute_fft_db(iq, sample_rate, smooth_bins=6)

    def bench_occupancy():
        estimate_occupancy(iq, sample_rate, snr_threshold_db=6.0, min_bw_hz=200)

    def bench_peaks():
        fft_db, bin_hz, _, _ = compute_fft_db(iq, sample_rate, smooth_bins=4)
        detect_peaks(fft_db, bin_hz=bin_hz, min_snr_db=6.0, max_peaks=8)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "params": {
            "sample_rate": sample_rate,
            "fft_size": fft_size,
            "iterations": iterations,
        },
        "results": {
            "compute_fft_db": _time_call(bench_fft, iterations),
            "estimate_occupancy": _time_call(bench_occupancy, iterations),
            "detect_peaks": _time_call(bench_peaks, iterations),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark DSP pipeline functions")
    parser.add_argument("--sample-rate", type=int, default=48000)
    parser.add_argument("--fft-size", type=int, default=8192)
    parser.add_argument("--iterations", type=int, default=80)
    parser.add_argument("--output", type=str, default="")
    args = parser.parse_args()

    report = run_benchmark(
        sample_rate=args.sample_rate,
        fft_size=args.fft_size,
        iterations=args.iterations,
    )

    rendered = json.dumps(report, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered + "\n")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
