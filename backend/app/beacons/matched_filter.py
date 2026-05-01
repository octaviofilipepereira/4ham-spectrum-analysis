# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
NCDXF Beacon Slot Detector — matched filter & dash-level meter.

Responsibilities (all within a single 10-second slot window):

  1. ID confirmation  — cross-correlate audio against a synthetic CW template
                        for the expected callsign (@22 WPM).  Output:
                        id_confirmed (bool) + id_confidence (float 0..1)

  2. Dash detection   — measure RMS power in each of the 4 dash windows and
                        compare against a noise floor estimated from the guard
                        region.  Output: dash_levels_detected (0..4) +
                        individual snr_db_* values.

  3. Drift measurement — timestamp of the energy onset in the CW ID region
                         vs. expected slot start, expressed in milliseconds.

All processing is synchronous (called from the scheduler in an executor
thread or inline — caller decides).  No async, no I/O.

Template synthesis
------------------
CW element timings at 22 WPM (PARIS standard, 1 WPM = 1200 ms/dit):
    dit_ms = 1200 / 22 ≈ 54.5 ms
    dah_ms = 3 × dit_ms ≈ 163.6 ms
    inter_element_gap_ms = dit_ms
    inter_char_gap_ms    = 3 × dit_ms
    inter_word_gap_ms    = 7 × dit_ms

Template is a bipolar square envelope (+1.0 tone, 0.0 silence) at the
target sample rate.  Cross-correlation is normalised so the peak is 1.0
when the input is a perfect, noise-free match.  In practice, id_confirmed
when normalised_peak ≥ CONFIRM_THRESHOLD (default 0.18 — empirically robust
down to ~6 dB SNR in the ID region).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np

from .catalog import (
    CW_ID_WPM,
    DASH_WINDOWS,
    SLOT_SECONDS,
)

# Confirmation threshold for the normalised cross-correlation peak.
# 0.18 is conservative enough to survive strong multipath at low SNR.
CONFIRM_THRESHOLD: float = 0.18

# Minimum SNR (dB) above noise floor to count a dash as "detected"
DASH_DETECT_THRESHOLD_DB: float = 3.0

# Noise floor is estimated from [6.5 s .. 9.5 s] of the slot (guard region)
_NOISE_WIN_START_S: float = 6.5
_NOISE_WIN_END_S: float   = 9.5

# CW ID onset window to search for drift measurement
_ID_ONSET_START_S: float = 0.0
_ID_ONSET_END_S: float   = 1.5


# ── Morse code table (minimal: only characters used in callsigns) ─────────────

_MORSE: dict[str, str] = {
    "A": ".-",   "B": "-...", "C": "-.-.", "D": "-..",  "E": ".",
    "F": "..-.", "G": "--.",  "H": "....", "I": "..",   "J": ".---",
    "K": "-.-",  "L": ".-..", "M": "--",   "N": "-.",   "O": "---",
    "P": ".--.", "Q": "--.-", "R": ".-.",  "S": "...",  "T": "-",
    "U": "..-",  "V": "...-", "W": ".--",  "X": "-..-", "Y": "-.--",
    "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--",
    "4": "....-", "5": ".....", "6": "-....", "7": "--...",
    "8": "---..", "9": "----.",
    "/": "-..-.",
}


def _build_cw_template(callsign: str, sample_rate: int, wpm: float = CW_ID_WPM) -> np.ndarray:
    """Synthesise a bipolar CW envelope for *callsign* at *wpm*."""
    dit_samples = int((1200.0 / wpm / 1000.0) * sample_rate)
    dah_samples = 3 * dit_samples
    gap_samples = dit_samples           # inter-element
    char_gap    = 3 * dit_samples       # inter-character (includes the trailing gap)

    samples: list[np.ndarray] = []
    for i, ch in enumerate(callsign.upper()):
        code = _MORSE.get(ch)
        if code is None:
            continue
        for j, element in enumerate(code):
            length = dah_samples if element == "-" else dit_samples
            samples.append(np.ones(length, dtype=np.float32))
            if j < len(code) - 1:
                samples.append(np.zeros(gap_samples, dtype=np.float32))
        if i < len(callsign) - 1:
            samples.append(np.zeros(char_gap, dtype=np.float32))
    if not samples:
        return np.zeros(dit_samples, dtype=np.float32)
    return np.concatenate(samples)


class SlotDetector:
    """Detect NCDXF beacon content in a single 10 s audio window.

    Parameters
    ----------
    callsign : str
        The callsign expected to transmit in this slot (e.g. "CS3B").
    sample_rate : int
        Sample rate of the audio array passed to :meth:`detect` (Hz).
    slot_start_utc : datetime
        UTC timestamp of the nominal slot boundary (for drift calculation).
    confirm_threshold : float
        Normalised cross-correlation peak threshold (default 0.18).
    dash_detect_db : float
        Minimum SNR (dB) over noise floor to count a dash (default 3.0).
    """

    def __init__(
        self,
        callsign: str,
        sample_rate: int,
        slot_start_utc: datetime,
        confirm_threshold: float = CONFIRM_THRESHOLD,
        dash_detect_db: float = DASH_DETECT_THRESHOLD_DB,
    ) -> None:
        self._callsign = callsign.upper()
        self._sr = int(sample_rate)
        self._slot_start_utc = slot_start_utc
        self._confirm_threshold = confirm_threshold
        self._dash_detect_db = dash_detect_db
        # Pre-build the template (cached for this instance)
        self._template = _build_cw_template(self._callsign, self._sr)

    def detect(self, audio: np.ndarray) -> dict[str, Any]:
        """Run all detectors against *audio* and return an observation dict.

        Returns
        -------
        dict with keys: detected, id_confirmed, id_confidence, drift_ms,
        dash_levels_detected, snr_db_100w, snr_db_10w, snr_db_1w,
        snr_db_100mw.
        """
        result: dict[str, Any] = {
            "detected": False,
            "id_confirmed": False,
            "id_confidence": 0.0,
            "drift_ms": None,
            "dash_levels_detected": 0,
            "snr_db_100w": None,
            "snr_db_10w": None,
            "snr_db_1w": None,
            "snr_db_100mw": None,
        }

        if audio is None or len(audio) == 0:
            return result

        # Normalise audio amplitude
        peak = np.max(np.abs(audio))
        if peak < 1e-9:
            return result
        audio_n = audio / peak

        # ── Noise floor estimate ────────────────────────────────────────────
        noise_rms = self._noise_floor(audio_n)

        # ── Dash detection ──────────────────────────────────────────────────
        dash_snrs: list[Optional[float]] = []
        snr_keys = ("snr_db_100w", "snr_db_10w", "snr_db_1w", "snr_db_100mw")

        for (start_s, end_s, _power_w), key in zip(DASH_WINDOWS, snr_keys):
            snr = self._measure_window_snr(audio_n, start_s, end_s, noise_rms)
            result[key] = round(float(snr), 2) if snr is not None else None
            dash_snrs.append(snr)

        # Count detected dashes (from strongest down, stopping at first miss)
        dashes = 0
        for snr in dash_snrs:
            if snr is not None and snr >= self._dash_detect_db:
                dashes += 1
            else:
                break  # NCDXF power steps down — a gap means higher powers also dropped
        result["dash_levels_detected"] = dashes

        # ── ID confirmation ─────────────────────────────────────────────────
        # Only examine the first ~1.5 s of the slot (ID window)
        id_end = int(_ID_ONSET_END_S * self._sr)
        id_audio = audio_n[:id_end]
        confidence, drift_ms = self._id_correlation(id_audio)
        result["id_confidence"] = round(float(confidence), 4)
        result["id_confirmed"] = bool(confidence >= self._confirm_threshold)
        if drift_ms is not None:
            result["drift_ms"] = round(float(drift_ms), 1)

        # Detected = any dash heard OR ID confirmed
        result["detected"] = dashes > 0 or result["id_confirmed"]

        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _noise_floor(self, audio_n: np.ndarray) -> float:
        """Estimate RMS noise power from the guard region of the slot."""
        s0 = int(_NOISE_WIN_START_S * self._sr)
        s1 = int(_NOISE_WIN_END_S * self._sr)
        region = audio_n[s0:s1]
        if len(region) < 64:
            # Guard region not available (short window); use whole audio
            return float(np.sqrt(np.mean(audio_n ** 2)))
        return float(np.sqrt(np.mean(region ** 2)))

    def _measure_window_snr(
        self,
        audio_n: np.ndarray,
        start_s: float,
        end_s: float,
        noise_rms: float,
    ) -> Optional[float]:
        """Return SNR (dB) of audio in [start_s, end_s] vs noise_rms."""
        s0 = int(start_s * self._sr)
        s1 = int(end_s * self._sr)
        region = audio_n[s0:s1]
        if len(region) < 8:
            return None
        rms = float(np.sqrt(np.mean(region ** 2)))
        if noise_rms < 1e-9:
            return None
        snr_linear = rms / noise_rms
        return 20.0 * math.log10(max(snr_linear, 1e-6))

    def _id_correlation(
        self,
        id_audio: np.ndarray,
    ) -> tuple[float, Optional[float]]:
        """
        Normalised cross-correlation of id_audio against self._template.

        Returns (confidence, drift_ms):
          confidence — normalised peak (0..1)
          drift_ms   — delay of peak vs. expected t=0 in the slot; positive
                       means the ID started late
        """
        tmpl = self._template
        if len(id_audio) < len(tmpl) // 2:
            return 0.0, None

        # Pad to same length for FFT-based correlation
        n = len(id_audio) + len(tmpl) - 1
        n_fft = 1 << (n - 1).bit_length()  # next power of 2

        X = np.fft.rfft(id_audio, n=n_fft)
        T = np.fft.rfft(tmpl, n=n_fft)
        corr = np.fft.irfft(X * np.conj(T), n=n_fft)[:n]

        # Normalise by the energy of the template
        tmpl_energy = float(np.sum(tmpl ** 2))
        if tmpl_energy < 1e-12:
            return 0.0, None
        signal_rms = float(np.sqrt(np.mean(id_audio[:len(tmpl)] ** 2))) if len(id_audio) >= len(tmpl) else 1.0
        norm = tmpl_energy * max(signal_rms, 1e-9)
        corr_norm = corr / norm

        peak_idx = int(np.argmax(corr_norm))
        confidence = float(np.clip(corr_norm[peak_idx], 0.0, 1.0))

        # drift_ms: peak_idx == 0 means template starts at sample 0 (no drift)
        drift_ms = (peak_idx / self._sr) * 1000.0 if confidence >= self._confirm_threshold else None

        return confidence, drift_ms
