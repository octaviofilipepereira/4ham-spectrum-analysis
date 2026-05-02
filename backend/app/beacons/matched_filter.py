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
from typing import Any, Optional, Sequence

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

# Weak-copy detection can combine sub-threshold ID evidence with an ordered
# dash sequence. The 100 W dash remains the anchor; later power steps only add
# bonus when the sequence still makes physical sense.
DETECT_SCORE_THRESHOLD: float = 1.25

# Noise floor is estimated from [6.5 s .. 9.5 s] of the slot (guard region)
_NOISE_WIN_START_S: float = 6.5
_NOISE_WIN_END_S: float   = 9.5

# Search enough of the slot to cover the full NCDXF CW ID plus a short guard.
_MIN_ID_WINDOW_S: float = 1.5
_ID_WINDOW_GUARD_S: float = 0.4

# Valid IDs start at the slot boundary; later matches are too ambiguous to use
# for confirmation.
_MAX_CONFIRM_DRIFT_MS: float = 600.0


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


def _dash_evidence_ratio(lead_dash_snr_db: Optional[float], dash_detect_db: float) -> float:
    if lead_dash_snr_db is None or dash_detect_db <= 0.0:
        return 0.0
    return max(0.0, float(lead_dash_snr_db)) / dash_detect_db


def _sequence_dash_evidence_ratio(
    dash_snrs: Sequence[Optional[float]],
    dash_detect_db: float,
) -> float:
    if not dash_snrs:
        return 0.0

    ratios = [_dash_evidence_ratio(snr, dash_detect_db) for snr in dash_snrs]
    lead_ratio = ratios[0]
    if lead_ratio <= 0.0:
        return 0.0

    sequence_ratio = lead_ratio
    running_prefix = min(1.0, lead_ratio)
    for ratio, weight in zip(ratios[1:], (0.35, 0.20, 0.10)):
        running_prefix = min(running_prefix, ratio)
        if running_prefix <= 0.0:
            break
        sequence_ratio += weight * running_prefix

    return sequence_ratio


def _combined_detect_score(
    confidence: float,
    dash_snrs: Sequence[Optional[float]],
    confirm_threshold: float,
    dash_detect_db: float,
) -> float:
    id_ratio = max(0.0, float(confidence)) / max(confirm_threshold, 1e-9)
    dash_ratio = _sequence_dash_evidence_ratio(dash_snrs, dash_detect_db)
    return id_ratio + dash_ratio


def _threshold_gap(current: Optional[float], threshold: float) -> Optional[float]:
    if current is None:
        return None
    return max(0.0, threshold - float(current))


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
        self._template = _build_cw_template(self._callsign, self._sr)
        self._id_window_samples = max(
            int(_MIN_ID_WINDOW_S * self._sr),
            len(self._template) + int(_ID_WINDOW_GUARD_S * self._sr),
        )

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
            "lead_dash_snr_db": None,
            "detect_score": 0.0,
            "detect_score_gap": None,
            "id_threshold_gap": None,
            "lead_dash_gap_db": None,
            "detected_via": "none",
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

        lead_dash_snr = dash_snrs[0] if dash_snrs else None
        result["lead_dash_snr_db"] = round(float(lead_dash_snr), 2) if lead_dash_snr is not None else None

        # Count detected dashes (from strongest down, stopping at first miss)
        dashes = 0
        for snr in dash_snrs:
            if snr is not None and snr >= self._dash_detect_db:
                dashes += 1
            else:
                break  # NCDXF power steps down — a gap means higher powers also dropped
        result["dash_levels_detected"] = dashes

        # ── ID confirmation ─────────────────────────────────────────────────
        # Examine enough of the slot to cover the complete CW ID, otherwise
        # longer callsigns become artificially ambiguous and valid copy drops out.
        id_audio = audio_n[: self._id_window_samples]
        confidence, drift_ms = self._id_correlation(id_audio)
        result["id_confidence"] = round(float(confidence), 4)
        result["id_confirmed"] = bool(
            confidence >= self._confirm_threshold
            and drift_ms is not None
            and drift_ms <= _MAX_CONFIRM_DRIFT_MS
        )
        if result["id_confirmed"] and drift_ms is not None:
            result["drift_ms"] = round(float(drift_ms), 1)

        detect_score = _combined_detect_score(
            confidence,
            dash_snrs,
            self._confirm_threshold,
            self._dash_detect_db,
        )
        result["detect_score"] = round(float(detect_score), 4)
        result["detect_score_gap"] = round(
            float(max(0.0, DETECT_SCORE_THRESHOLD - detect_score)), 4
        )
        result["id_threshold_gap"] = round(
            float(_threshold_gap(confidence, self._confirm_threshold) or 0.0), 4
        )
        result["lead_dash_gap_db"] = round(
            float(_threshold_gap(lead_dash_snr, self._dash_detect_db) or 0.0), 2
        )

        # Detected = any dash heard OR a raw ID peak above threshold. Strict
        # ambiguity/drift gating remains reserved for id_confirmed.
        if dashes > 0:
            result["detected"] = True
            result["detected_via"] = "dash"
        elif confidence >= self._confirm_threshold:
            result["detected"] = True
            result["detected_via"] = "id"
        elif detect_score >= DETECT_SCORE_THRESHOLD:
            result["detected"] = True
            result["detected_via"] = "combined"

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
        Correlate id_audio against the expected callsign template.

        Returns (confidence, drift_ms):
          confidence — score for the expected callsign template
          drift_ms   — delay of the best expected-template peak
        """
        return self._correlation_peak(id_audio, self._template)

    def _correlation_peak(
        self,
        id_audio: np.ndarray,
        template: np.ndarray,
    ) -> tuple[float, Optional[float]]:
        min_overlap = max(1, len(template) // 2)
        if len(id_audio) < min_overlap:
            return 0.0, None

        x = id_audio.astype(np.float32, copy=False)
        x = x - float(np.mean(x))

        n = len(x) + len(template) - 1
        n_fft = 1 << (n - 1).bit_length()

        X = np.fft.rfft(x, n=n_fft)
        T = np.fft.rfft(template, n=n_fft)
        corr = np.fft.irfft(X * np.conj(T), n=n_fft)[:n]

        signal_ref = x[: min(len(x), len(template))]
        norm = float(np.sqrt(np.sum(template ** 2)) * max(np.linalg.norm(signal_ref), 1e-9))
        if norm < 1e-12:
            return 0.0, None
        corr_norm = corr / norm

        # Ignore peaks whose template overlap is too small to be specific.
        max_start = max(0, len(x) - min_overlap)
        valid_corr = corr_norm[: max_start + 1]
        if len(valid_corr) == 0:
            return 0.0, None

        peak_idx = int(np.argmax(valid_corr))
        confidence = float(np.clip(valid_corr[peak_idx], 0.0, 1.0))
        drift_ms = (peak_idx / self._sr) * 1000.0

        return confidence, drift_ms
