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
    noise_floor_db = float(np.percentile(fft_db, 20))
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
                "snr_db": snr_db,
                "occupied": True
            }
        )

    return results


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
