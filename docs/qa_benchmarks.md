<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-02-22 16:27:19 UTC
-->

# DSP performance benchmark

Use this benchmark to compare DSP performance across Linux platforms (PC and Raspberry Pi) with the same parameters.

## Command

Run from repository root:

`/path/to/.venv/bin/python backend/benchmarks/benchmark_dsp.py --sample-rate 48000 --fft-size 8192 --iterations 80 --output data/bench_linux.json`


## Output

The report includes:

- Platform metadata (`system`, `release`, `machine`, `python`)
- Benchmark parameters
- Timing metrics per function (`min`, `max`, `mean`, `p95` in milliseconds)

Functions covered:

- `compute_fft_db`
- `estimate_occupancy`
- `detect_peaks`

## Suggested comparison workflow

1. Run exactly the same command on each target platform.
2. Save JSON reports with platform-specific filenames.
3. Compare `mean_ms` and `p95_ms` per function.
4. Track regressions in version control along with code changes.
