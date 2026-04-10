# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 16:27:19 UTC

import numpy as np


def _find_segments(mask):
    segments = []
    start = None
    for idx, value in enumerate(mask):
        if value and start is None:
            start = idx
        elif not value and start is not None:
            segments.append((start, idx - 1))
            start = None
    if start is not None:
        segments.append((start, len(mask) - 1))
    return segments


def classify_mode_heuristic(bandwidth_hz, snr_db=None, frequency_hz=None):
    if bandwidth_hz is None:
        return "Unknown", 0.25

    bw = float(max(0.0, bandwidth_hz))
    if bw < 350:
        mode = "CW"
    elif bw < 1200:
        mode = "FSK/PSK"
    elif bw < 3200:
        mode = "SSB"
    elif bw < 9000:
        mode = "AM"
    elif bw < 20000:
        mode = "FM"
    else:
        mode = "Unknown"

    # On HF amateur bands (< 30 MHz) AM is virtually unused — reclassify
    # bandwidth-only "AM" as "SSB" ONLY when the measured bandwidth is
    # still within SSB voice range (≤ 2800 Hz).  Wider signals are
    # broadband noise / interference, not SSB voice.
    if mode == "AM" and frequency_hz is not None:
        freq = float(frequency_hz)
        _is_10m_am_window = 29_000_000 <= freq <= 29_700_000
        if freq < 30_000_000 and not _is_10m_am_window and bw <= 2800:
            mode = "SSB"

    snr = 0.0 if snr_db is None else float(max(0.0, snr_db))
    snr_factor = min(1.0, snr / 20.0)
    base = 0.5 if mode != "Unknown" else 0.25
    confidence = min(0.95, base + 0.4 * snr_factor)
    return mode, float(confidence)


def estimate_noise_floor(fft_db, percentile=20):
    if not fft_db:
        return None
    return float(np.percentile(fft_db, percentile))


def detect_peaks(fft_db, bin_hz, min_snr_db=6.0, max_peaks=6):
    if not fft_db:
        return []
    noise_floor_db = estimate_noise_floor(fft_db, 20)
    if noise_floor_db is None:
        return []
    threshold_db = noise_floor_db + min_snr_db
    peaks = []
    for idx in range(1, len(fft_db) - 1):
        value = fft_db[idx]
        if value >= threshold_db and value >= fft_db[idx - 1] and value >= fft_db[idx + 1]:
            peaks.append((idx, value))
    peaks.sort(key=lambda item: item[1], reverse=True)
    peaks = peaks[:max_peaks]
    center_idx = (len(fft_db) - 1) / 2.0
    return [
        {
            "offset_hz": float((idx - center_idx) * bin_hz),
            "snr_db": float(value - noise_floor_db)
        }
        for idx, value in peaks
    ]


def apply_agc(iq_samples, target_rms=0.25, max_gain_db=30.0):
    if iq_samples is None or len(iq_samples) == 0:
        return iq_samples, 0.0
    rms = np.sqrt(np.mean(np.abs(iq_samples) ** 2))
    if rms <= 0:
        return iq_samples, 0.0
    gain = target_rms / rms
    gain_db = 20.0 * np.log10(gain + 1e-12)
    gain_db = float(np.clip(gain_db, -max_gain_db, max_gain_db))
    gain = 10 ** (gain_db / 20.0)
    return iq_samples * gain, gain_db


def apply_agc_smoothed(iq_samples, state, target_rms=0.25, max_gain_db=30.0, alpha=0.2):
    if iq_samples is None or len(iq_samples) == 0:
        return iq_samples, 0.0
    rms = np.sqrt(np.mean(np.abs(iq_samples) ** 2))
    if rms <= 0:
        return iq_samples, 0.0
    gain = target_rms / rms
    gain_db = 20.0 * np.log10(gain + 1e-12)
    gain_db = float(np.clip(gain_db, -max_gain_db, max_gain_db))
    prev = None
    if isinstance(state, dict):
        prev = state.get("gain_db")
    if prev is None:
        smoothed = gain_db
    else:
        smoothed = (1 - alpha) * prev + alpha * gain_db
    if isinstance(state, dict):
        state["gain_db"] = smoothed
    gain = 10 ** (smoothed / 20.0)
    return iq_samples * gain, float(smoothed)


def estimate_occupancy(
    iq_samples,
    sample_rate,
    threshold_dbm=-95.0,
    adapt=True,
    snr_threshold_db=6.0,
    min_bw_hz=500
):
    """Estimate occupancy from IQ samples using FFT-based detection."""
    if iq_samples is None or len(iq_samples) == 0:
        return []

    fft_db, bin_hz, _, _ = compute_fft_db(iq_samples, sample_rate, smooth_bins=6)
    if not fft_db:
        return []

    power_db = compute_power_db(iq_samples)
    noise_floor_db = estimate_noise_floor(fft_db, 20)
    if noise_floor_db is None:
        return []
    threshold_db = noise_floor_db + snr_threshold_db
    mask = np.array(fft_db) > threshold_db
    segments = _find_segments(mask)

    if not segments:
        if adapt:
            threshold_dbm = max(threshold_dbm, power_db - 10.0)
        occupied = power_db > threshold_dbm
        return [
            {
                "frequency_hz": None,
                "bandwidth_hz": int(sample_rate),
                "power_dbm": float(power_db),
                "threshold_dbm": float(threshold_dbm),
                "noise_floor_db": float(noise_floor_db),
                "snr_db": float(power_db - threshold_dbm),
                "occupied": bool(occupied)
            }
        ]

    results = []
    bins = len(fft_db)
    center_idx = (bins - 1) / 2.0
    for start, end in segments:
        bw_hz = int((end - start + 1) * bin_hz)
        if bw_hz < min_bw_hz:
            continue
        peak_db = float(np.max(fft_db[start : end + 1]))
        snr_db = float(peak_db - noise_floor_db)
        mid_idx = (start + end) / 2.0
        offset_hz = float((mid_idx - center_idx) * bin_hz)
        results.append(
            {
                "frequency_hz": None,
                "offset_hz": offset_hz,
                "bandwidth_hz": bw_hz,
                "power_dbm": float(power_db),
                "threshold_dbm": float(threshold_db),
                "noise_floor_db": float(noise_floor_db),
                "snr_db": snr_db,
                "occupied": True
            }
        )

    if results:
        return results

    if adapt:
        threshold_dbm = max(threshold_dbm, power_db - 10.0)
    occupied = power_db > threshold_dbm
    return [
        {
            "frequency_hz": None,
            "bandwidth_hz": int(sample_rate),
            "power_dbm": float(power_db),
            "threshold_dbm": float(threshold_dbm),
            "noise_floor_db": float(noise_floor_db),
            "snr_db": float(power_db - threshold_dbm),
            "occupied": bool(occupied)
        }
    ]


def compute_fft_db(iq_samples, sample_rate, smooth_bins=4):
    """Compute FFT magnitude in dB (relative to peak) and return bins."""
    if iq_samples is None or len(iq_samples) == 0:
        return [], 0.0, 0.0, 0.0

    window = np.hanning(len(iq_samples))
    spectrum = np.fft.fftshift(np.fft.fft(iq_samples * window))
    power = np.abs(spectrum) ** 2
    peak = np.max(power) + 1e-12
    fft_db = 10.0 * np.log10(power / peak + 1e-12)
    if smooth_bins and smooth_bins > 1:
        kernel = np.ones(smooth_bins) / float(smooth_bins)
        fft_db = np.convolve(fft_db, kernel, mode="same")
    bin_hz = float(sample_rate) / float(len(iq_samples))
    return fft_db.tolist(), bin_hz, float(np.min(fft_db)), float(np.max(fft_db))


def compute_power_db(iq_samples):
    if iq_samples is None or len(iq_samples) == 0:
        return -120.0
    power_linear = np.mean(np.abs(iq_samples) ** 2)
    return float(10.0 * np.log10(power_linear + 1e-12))
