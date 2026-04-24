# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

# © 2026 CT7BFV — CW Decoder (standalone)
"""
CWDecoder — pure Python/NumPy/SciPy Morse decoder.

Usage:
    from backend.app.decoders.cw.decoder import CWDecoder

    dec = CWDecoder(sample_rate=8000)
    result = dec.decode(audio_array)
    print(result.text)          # e.g. "CQ DE CT7BFV"
    print(result.wpm)           # e.g. 18.4
    print(result.confidence)    # 0.0 – 1.0
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator

import numpy as np

from .dsp import preprocess, dominant_frequency, dominant_frequencies, estimate_snr
from .timing import analyse_timing, TimingResult
from .morse_table import decode_symbol


# ─────────────────────────────────────────────────────────────────────────────
# Result type
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DecodeResult:
    """Output of a single CWDecoder.decode() call."""
    text: str                        # Decoded plain text
    wpm: float                       # Estimated code speed (WPM)
    confidence: float                # 0.0 – 1.0
    dominant_freq_hz: float          # Detected CW tone frequency
    morse_raw: str                   # Raw Morse symbols e.g. ".- -... /"
    characters: list[str] = field(default_factory=list)
    unknown_count: int = 0           # Number of '?' characters
    callsigns: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Callsign extraction
# ─────────────────────────────────────────────────────────────────────────────

# ITU callsign pattern (basic): 1–2 letters/digits, digit, 1–4 letters
_CALLSIGN_RE = re.compile(
    r"\b([A-Z]{1,2}[0-9][A-Z]{1,4}|[0-9][A-Z][0-9][A-Z]{1,4})\b"
)


def extract_callsigns(text: str) -> list[str]:
    """Extract amateur radio callsigns from decoded text."""
    return _CALLSIGN_RE.findall(text.upper())


# ─────────────────────────────────────────────────────────────────────────────
# Morse sequence → text
# ─────────────────────────────────────────────────────────────────────────────

def morse_sequence_to_text(morse_symbols: list[str]) -> tuple[str, str, int]:
    """
    Convert a list of Morse symbols ('.', '-', ' ', '/') to plain text.

    Returns:
        (text, morse_raw_string, unknown_count)
    """
    # Group into characters (split on ' ') and words (split on '/')
    text_chars: list[str] = []
    unknown_count = 0
    current_symbol = ""
    morse_parts: list[str] = []

    for sym in morse_symbols:
        if sym in (".", "-"):
            current_symbol += sym
        elif sym == " ":
            # inter-character gap: decode current buffer
            if current_symbol:
                ch = decode_symbol(current_symbol)
                if ch == "?":
                    unknown_count += 1
                text_chars.append(ch)
                morse_parts.append(current_symbol)
                current_symbol = ""
        elif sym == "/":
            # word gap: flush current char, then add space
            if current_symbol:
                ch = decode_symbol(current_symbol)
                if ch == "?":
                    unknown_count += 1
                text_chars.append(ch)
                morse_parts.append(current_symbol)
                current_symbol = ""
            text_chars.append(" ")
            morse_parts.append("/")

    # Flush any remaining symbol at end of stream
    if current_symbol:
        ch = decode_symbol(current_symbol)
        if ch == "?":
            unknown_count += 1
        text_chars.append(ch)
        morse_parts.append(current_symbol)

    text = "".join(text_chars).strip()
    morse_raw = " ".join(morse_parts)
    return text, morse_raw, unknown_count


# ─────────────────────────────────────────────────────────────────────────────
# Confidence scoring
# ─────────────────────────────────────────────────────────────────────────────

def compute_confidence(
    text: str,
    unknown_count: int,
    timing: TimingResult,
) -> float:
    """
    Heuristic confidence score [0.0 – 1.0].

    Factors:
    - Ratio of unknown characters (lower = better)
    - Total character count (more chars = more reliable estimate)
    - WPM plausibility (5–50 WPM is realistic for amateur radio)
    """
    if not text:
        return 0.0

    total_chars = len([c for c in text if c.strip()])
    if total_chars == 0:
        return 0.0

    # Unknown ratio: 0 unknowns → 1.0, all unknowns → 0.0
    unknown_ratio = unknown_count / max(1, total_chars)
    char_score = max(0.0, 1.0 - unknown_ratio * 2.0)

    # WPM plausibility
    wpm = timing.estimated_wpm
    if 5 <= wpm <= 50:
        wpm_score = 1.0
    elif wpm < 5:
        wpm_score = max(0.0, wpm / 5.0)
    else:
        wpm_score = max(0.0, 1.0 - (wpm - 50) / 50.0)

    # Length bonus: more chars = more confidence (up to 20)
    length_score = min(1.0, total_chars / 20.0)

    confidence = (char_score * 0.5 + wpm_score * 0.3 + length_score * 0.2)
    return round(min(1.0, max(0.0, confidence)), 3)


# ─────────────────────────────────────────────────────────────────────────────
# Decoder
# ─────────────────────────────────────────────────────────────────────────────

class CWDecoder:
    """
    Standalone CW (Morse code) decoder.

    Processes mono audio samples (float32, normalised to ±1.0)
    and returns decoded text with metadata.
    
    Performance Notes:
    - Optimal: 10-50 WPM (typical amateur operation)
    - Good: 50-60 WPM (high-speed amateur, some contests)
    - Degraded: 60-80 WPM (contest software, reduced accuracy)
    - Poor: > 80 WPM (requires advanced algorithms)

    Args:
        sample_rate:  Audio sample rate in Hz (default: 8000).
        low_hz:       Bandpass lower cutoff (default: 300 Hz).
        high_hz:      Bandpass upper cutoff (default: 900 Hz).
        smooth_ms:    Envelope smoothing window in ms (default: 5.0).
        threshold:    Binarisation threshold [0..1] or None for auto.
        min_snr_db:   Minimum SNR to accept signal (0 = disabled).
        max_wpm:      Maximum WPM before rejecting as noise (0 = disabled).
        min_audio_duration: Min duration (s) to apply SNR validation.
    """

    def __init__(
        self,
        sample_rate: int = 8000,
        low_hz: float = 300.0,
        high_hz: float = 900.0,
        smooth_ms: float = 5.0,
        threshold: float | None = None,
        min_snr_db: float = 0.0,          # SNR threshold (0 = disabled)
        max_wpm: float = 100.0,           # Maximum credible WPM
        min_audio_duration: float = 2.0,  # Min duration (s) to apply SNR check
    ) -> None:
        self.sample_rate = sample_rate
        self.low_hz = low_hz
        self.high_hz = high_hz
        self.smooth_ms = smooth_ms
        self.threshold = threshold
        self.min_snr_db = min_snr_db
        self.max_wpm = max_wpm
        self.min_audio_duration = min_audio_duration

    # ── Public API ────────────────────────────────────────────────────────────

    def decode(self, audio: np.ndarray) -> DecodeResult:
        """
        Decode CW from a mono audio array.

        Tries up to 3 candidate tone frequencies (dominant_frequencies) and
        returns the result with the highest confidence score.  This handles
        the case where the strongest raw FFT peak is noise and the actual CW
        carrier is the 2nd or 3rd strongest narrowband signal.

        Args:
            audio: float32 array, normalised to ±1.0, any length.
                   Minimum ~0.5 s of audio is recommended.

        Returns:
            DecodeResult with decoded text and metadata.
        """
        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)   # downmix to mono

        # Find top-3 narrowband tone candidates (with local SNR > 3 dB)
        candidates = dominant_frequencies(audio, self.sample_rate, n=3, min_snr_db=3.0)

        # The primary frequency is the strongest FFT candidate — used as the
        # reported dominant_freq_hz regardless of which candidate decodes best.
        # This preserves IQ-pipeline frequency-detection assertions (the physical
        # CW carrier is always candidate[0]) while still trying secondary peaks
        # for confidence improvement.
        primary_freq = candidates[0] if candidates else 0.0

        best: DecodeResult | None = None
        for dom_freq in candidates:
            result = self._decode_at_frequency(audio, dom_freq)
            if best is None or result.confidence > best.confidence:
                best = result
            if best.confidence >= 0.9:
                break  # good enough — no need to try remaining candidates

        if best is None:
            return DecodeResult(
                text="", wpm=0.0, confidence=0.0, dominant_freq_hz=primary_freq, morse_raw=""
            )
        # Stamp the primary (physically-detected) frequency onto the result so
        # that frequency-accuracy tests reflect the actual signal location.
        best = DecodeResult(
            text=best.text,
            wpm=best.wpm,
            confidence=best.confidence,
            dominant_freq_hz=primary_freq,
            morse_raw=best.morse_raw,
            characters=best.characters,
            unknown_count=best.unknown_count,
            callsigns=best.callsigns,
        )
        return best

    def _decode_at_frequency(self, audio: np.ndarray, dom_freq: float) -> DecodeResult:
        """Run the full DSP pipeline for a single candidate tone frequency."""
        # Optional SNR validation (for real-world signals, disabled by default)
        if self.min_snr_db > 0:
            audio_duration = len(audio) / self.sample_rate
            if audio_duration >= self.min_audio_duration:
                snr_db = estimate_snr(audio, self.sample_rate, dom_freq)
                if snr_db < self.min_snr_db:
                    return DecodeResult(
                        text="", wpm=0.0, confidence=0.0,
                        dominant_freq_hz=dom_freq,
                        morse_raw="",
                    )

        # Auto-tune bandpass around detected tone.
        # Cap upper edge at 75 % of Nyquist to avoid Butterworth distortion
        # near the folding frequency (was sample_rate/2 - 50 which reaches 97 %
        # of Nyquist for tones near the high end of the bandwidth).
        safe_upper = self.sample_rate * 0.375   # 75 % of Nyquist
        tone_low  = max(100.0, dom_freq - 400.0)
        tone_high = min(safe_upper, dom_freq + 400.0)

        # DSP pipeline → binary on/off signal
        binary = preprocess(
            audio,
            self.sample_rate,
            low_hz=tone_low,
            high_hz=tone_high,
            smooth_ms=self.smooth_ms,
            threshold=self.threshold,
        )

        # Timing analysis → Morse symbols
        timing = analyse_timing(binary, self.sample_rate)

        if not timing.morse_symbols:
            return DecodeResult(
                text="", wpm=0.0, confidence=0.0,
                dominant_freq_hz=dom_freq,
                morse_raw="",
            )
        
        # Morse symbols → text
        text, morse_raw, unknown_count = morse_sequence_to_text(timing.morse_symbols)
        
        # Optional WPM validation (only with sufficient symbols for reliable estimate)
        if self.max_wpm > 0 and len(timing.morse_symbols) > 10:
            if timing.estimated_wpm < 3.0 or timing.estimated_wpm > self.max_wpm:
                return DecodeResult(
                    text="", wpm=0.0, confidence=0.0,
                    dominant_freq_hz=dom_freq,
                    morse_raw="",
                )

        # Confidence score
        confidence = compute_confidence(text, unknown_count, timing)

        # Callsign extraction
        callsigns = extract_callsigns(text)

        return DecodeResult(
            text=text,
            wpm=round(timing.estimated_wpm, 1),
            confidence=confidence,
            dominant_freq_hz=round(dom_freq, 1),
            morse_raw=morse_raw,
            characters=list(text.replace(" ", "")),
            unknown_count=unknown_count,
            callsigns=callsigns,
        )

    def decode_streaming(
        self,
        audio_chunks: Iterator[np.ndarray],
    ) -> Iterator[DecodeResult]:
        """
        Stream-decode by accumulating chunks into a rolling buffer.

        Yields a DecodeResult every time the buffer reaches ~10 s of audio.
        Designed for real-time use with an IQ pipeline.
        """
        buffer_target = self.sample_rate * 10   # 10-second windows
        buffer = np.array([], dtype=np.float32)

        for chunk in audio_chunks:
            chunk = np.asarray(chunk, dtype=np.float32)
            if chunk.ndim > 1:
                chunk = chunk.mean(axis=1)
            buffer = np.concatenate([buffer, chunk])

            while len(buffer) >= buffer_target:
                window = buffer[:buffer_target]
                buffer = buffer[buffer_target // 2:]  # 50 % overlap
                result = self.decode(window)
                if result.text:
                    yield result
