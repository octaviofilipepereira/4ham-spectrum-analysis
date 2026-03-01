# © 2026 CT7BFV — CW DSP utilities
"""
Digital Signal Processing for CW decoding.

Pipeline:
  audio (float32, mono) → bandpass → envelope → normalised float32 [0..1]
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt, hilbert


# ─────────────────────────────────────────────────────────────────────────────
# Bandpass filter
# ─────────────────────────────────────────────────────────────────────────────

def bandpass_filter(
    audio: np.ndarray,
    sample_rate: int,
    low_hz: float = 300.0,
    high_hz: float = 900.0,
    order: int = 4,
) -> np.ndarray:
    """
    Butterworth bandpass filter to isolate the CW tone.

    Typical CW audio tones fall in 300–900 Hz after SSB demodulation.
    The filter suppresses carrier leakage and noise outside that band.
    """
    nyq = sample_rate / 2.0
    low = max(low_hz / nyq, 1e-4)
    high = min(high_hz / nyq, 1.0 - 1e-4)
    sos = butter(order, [low, high], btype="bandpass", output="sos")
    return sosfilt(sos, audio).astype(np.float32)


# ─────────────────────────────────────────────────────────────────────────────
# Envelope detector
# ─────────────────────────────────────────────────────────────────────────────

def envelope_detector(audio: np.ndarray) -> np.ndarray:
    """
    Extract signal envelope via Hilbert transform (analytic signal).

    Returns the instantaneous amplitude (envelope), always ≥ 0.
    More accurate than simple rectification + low-pass.
    """
    analytic = hilbert(audio)
    envelope = np.abs(analytic).astype(np.float32)
    return envelope


def smooth_envelope(envelope: np.ndarray, window_samples: int = 20) -> np.ndarray:
    """
    Light moving-average smoothing to remove high-frequency ripple
    while preserving key rise/fall edges.
    """
    if window_samples < 2:
        return envelope
    kernel = np.ones(window_samples, dtype=np.float32) / window_samples
    return np.convolve(envelope, kernel, mode="same")


# ─────────────────────────────────────────────────────────────────────────────
# Normalisation & binarisation
# ─────────────────────────────────────────────────────────────────────────────

def normalise(signal: np.ndarray) -> np.ndarray:
    """Normalise signal to [0, 1]."""
    peak = signal.max()
    if peak < 1e-9:
        return np.zeros_like(signal)
    return (signal / peak).astype(np.float32)


def binarise(
    envelope: np.ndarray,
    threshold: float | None = None,
) -> np.ndarray:
    """
    Convert normalised envelope to binary (on/off) signal.

    If threshold is None, uses Otsu-style midpoint between noise floor
    and signal peak to handle variable SNR.

    Returns int8 array of 0s and 1s.
    """
    norm = normalise(envelope)

    if threshold is None:
        # Estimate noise floor as median of lower 30 % of samples
        sorted_vals = np.sort(norm)
        noise_floor = float(np.median(sorted_vals[: max(1, len(sorted_vals) // 3)]))
        signal_peak = float(np.percentile(sorted_vals, 95))
        threshold = noise_floor + (signal_peak - noise_floor) * 0.5
        threshold = max(threshold, 0.05)   # never below 5 %

    return (norm > threshold).astype(np.int8)


# ─────────────────────────────────────────────────────────────────────────────
# Dominant frequency estimation (FFT peak)
# ─────────────────────────────────────────────────────────────────────────────

def dominant_frequency(audio: np.ndarray, sample_rate: int) -> float:
    """
    Return the frequency bin with the highest power in 200–1200 Hz range.
    Useful for auto-centering the bandpass filter.
    """
    fft = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(len(audio), d=1.0 / sample_rate)
    mask = (freqs >= 200) & (freqs <= 1200)
    if not mask.any():
        return 700.0  # default CW tone
    idx = np.argmax(fft[mask])
    return float(freqs[mask][idx])


def estimate_snr(audio: np.ndarray, sample_rate: int, tone_hz: float) -> float:
    """
    Estimate Signal-to-Noise Ratio (SNR) in dB.
    
    Compares power in a narrow band around the detected tone
    versus power in noise bands away from the tone.
    
    Returns:
        SNR in dB (positive = signal above noise floor)
        Returns 0.0 if no clear tone detected
    """
    if len(audio) < sample_rate // 10:  # Need at least 100ms
        return 0.0
    
    fft = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(len(audio), d=1.0 / sample_rate)
    
    # Signal band: ±50 Hz around detected tone
    signal_mask = (freqs >= tone_hz - 50) & (freqs <= tone_hz + 50)
    signal_power = float(np.mean(fft[signal_mask] ** 2)) if signal_mask.any() else 0.0
    
    # Noise bands: 200-400 Hz and 1000-1200 Hz (away from typical CW)
    noise_mask = ((freqs >= 200) & (freqs <= 400)) | ((freqs >= 1000) & (freqs <= 1200))
    noise_power = float(np.mean(fft[noise_mask] ** 2)) if noise_mask.any() else 1e-10
    
    if noise_power < 1e-10 or signal_power < 1e-10:
        return 0.0
    
    snr_linear = signal_power / noise_power
    snr_db = 10.0 * np.log10(snr_linear)
    return float(snr_db)


# ─────────────────────────────────────────────────────────────────────────────
# Full preprocessing chain
# ─────────────────────────────────────────────────────────────────────────────

def preprocess(
    audio: np.ndarray,
    sample_rate: int,
    low_hz: float = 300.0,
    high_hz: float = 900.0,
    smooth_ms: float = 5.0,
    threshold: float | None = None,
) -> np.ndarray:
    """
    Full pipeline: bandpass → envelope → smooth → binarise.

    Args:
        audio:       Raw mono audio (float32 or int16 normalised to ±1).
        sample_rate: Hz.
        low_hz:      Bandpass lower cutoff.
        high_hz:     Bandpass upper cutoff.
        smooth_ms:   Smoothing window in ms (reduces glitches).
        threshold:   Binarisation threshold [0..1], or None for auto.

    Returns:
        int8 array of 0/1 values (tone off/on).
    """
    filtered  = bandpass_filter(audio, sample_rate, low_hz, high_hz)
    envelope  = envelope_detector(filtered)
    win       = max(1, int(sample_rate * smooth_ms / 1000.0))
    smoothed  = smooth_envelope(envelope, window_samples=win)
    binary    = binarise(smoothed, threshold=threshold)
    return binary
