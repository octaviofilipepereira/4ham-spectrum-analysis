import numpy as np


def estimate_occupancy(iq_samples, sample_rate, threshold_dbm=-95.0):
    """Estimate occupancy from IQ samples using a simple power metric."""
    if iq_samples is None or len(iq_samples) == 0:
        return []

    power_linear = np.mean(np.abs(iq_samples) ** 2)
    power_db = 10.0 * np.log10(power_linear + 1e-12)
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
