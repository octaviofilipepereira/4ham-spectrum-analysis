import numpy as np


def estimate_occupancy(iq_samples, sample_rate, threshold_dbm=-95.0, adapt=True):
    """Estimate occupancy from IQ samples using a simple power metric."""
    if iq_samples is None or len(iq_samples) == 0:
        return []

    power_linear = np.mean(np.abs(iq_samples) ** 2)
    power_db = 10.0 * np.log10(power_linear + 1e-12)
    if adapt:
        threshold_dbm = max(threshold_dbm, power_db - 10.0)
    occupied = power_db > threshold_dbm

    return [
        {
            "frequency_hz": None,
            "bandwidth_hz": int(sample_rate),
            "power_dbm": float(power_db),
            "threshold_dbm": float(threshold_dbm),
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
