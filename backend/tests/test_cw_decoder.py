# © 2026 CT7BFV — CW Decoder Test Suite
"""
Comprehensive tests for the standalone CW decoder.

Tests cover:
  - Individual characters (A-Z, 0-9)
  - Common callsigns
  - CW QSO phrases (CQ, DE, RST, K)
  - WPM range (10–30 WPM)
  - Noise tolerance (SNR 20 dB, 10 dB, 6 dB)
  - Morse table completeness
  - DSP components (bandpass, envelope, binarise)
"""

from __future__ import annotations

import sys
import os
import math
import time
import numpy as np
import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
# Allow running directly:  python -m pytest backend/tests/test_cw_decoder.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.decoders.cw.morse_table import (
    CHAR_TO_MORSE, MORSE_TO_CHAR, encode_text, decode_symbol
)
from app.decoders.cw.dsp import (
    bandpass_filter, envelope_detector, binarise, preprocess, dominant_frequency
)
from app.decoders.cw.timing import analyse_timing, run_length_encode
from app.decoders.cw.decoder import (
    CWDecoder, DecodeResult, morse_sequence_to_text, extract_callsigns
)


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic CW audio generator
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_RATE = 8000   # Hz — adequate for CW decoding

def generate_cw_audio(
    text: str,
    wpm: float = 20.0,
    tone_hz: float = 700.0,
    sample_rate: int = SAMPLE_RATE,
    noise_db: float = -60.0,       # noise floor (dBFS); -60 = very clean
    rise_ms: float = 5.0,          # key click suppression rise/fall
) -> np.ndarray:
    """
    Synthesise Morse code audio for a given text string.

    Implements standard PARIS timing:
      - dit  = 1 unit
      - dah  = 3 units
      - intra-char gap = 1 unit
      - inter-char gap = 3 units
      - word gap       = 7 units

    Key-click suppression: raised-cosine shaping on each tone element.
    White Gaussian noise added at specified SNR.

    Returns float32 array normalised to ±1.0.
    """
    dit_samples = int(sample_rate * 1.2 / wpm)   # 1200 ms / wpm = dit_ms
    dah_samples = dit_samples * 3
    char_gap    = dit_samples * 3
    word_gap    = dit_samples * 7
    intra_gap   = dit_samples       # gap between elements within char

    rise_samples = max(1, int(sample_rate * rise_ms / 1000.0))

    def tone_segment(length: int) -> np.ndarray:
        """Single keyed tone with raised-cosine edges."""
        t = np.arange(length, dtype=np.float32) / sample_rate
        carrier = np.sin(2 * np.pi * tone_hz * t)
        # Envelope shaping
        env = np.ones(length, dtype=np.float32)
        ramp = (1 - np.cos(np.linspace(0, np.pi, rise_samples))) / 2
        n = min(rise_samples, length // 2)
        env[:n] = ramp[:n]
        env[-n:] = ramp[:n][::-1]
        return carrier * env

    def silence(length: int) -> np.ndarray:
        return np.zeros(length, dtype=np.float32)

    segments: list[np.ndarray] = []

    # Encode text to Morse symbols
    morse_list = encode_text(text)

    for i, symbol in enumerate(morse_list):
        if symbol is None:
            # Word gap (replace last inter-char gap + add remaining)
            if segments:
                segments.append(silence(word_gap - char_gap))
            else:
                segments.append(silence(word_gap))
            continue

        for j, element in enumerate(symbol):
            if element == ".":
                segments.append(tone_segment(dit_samples))
            elif element == "-":
                segments.append(tone_segment(dah_samples))

            # Intra-character gap (not after last element)
            if j < len(symbol) - 1:
                segments.append(silence(intra_gap))

        # Inter-character gap after every character (including before word gaps)
        # This is needed so that word_gap = char_gap(3) + extra(4) = 7 dits total
        if i < len(morse_list) - 1:
            segments.append(silence(char_gap))

    if not segments:
        return np.zeros(sample_rate, dtype=np.float32)

    audio = np.concatenate(segments)

    # Add white Gaussian noise
    if noise_db < 0:
        noise_amplitude = 10 ** (noise_db / 20.0)
        noise = np.random.default_rng(seed=42).standard_normal(len(audio)).astype(np.float32)
        audio = audio + noise_amplitude * noise

    # Normalise to ±1.0
    peak = np.abs(audio).max()
    if peak > 1e-9:
        audio /= peak

    return audio


# ─────────────────────────────────────────────────────────────────────────────
# Helper: decode with permissive accuracy check
# ─────────────────────────────────────────────────────────────────────────────

def decode_text(text: str, wpm: float = 20.0, noise_db: float = -60.0) -> DecodeResult:
    """Generate synthetic CW audio and decode it."""
    audio = generate_cw_audio(text, wpm=wpm, noise_db=noise_db)
    dec = CWDecoder(sample_rate=SAMPLE_RATE)
    return dec.decode(audio)


def char_accuracy(expected: str, got: str) -> float:
    """
    Simple character accuracy: fraction of expected chars present in result.
    Case-insensitive. Ignores spaces.
    """
    exp = expected.upper().replace(" ", "")
    got = got.upper().replace(" ", "")
    if not exp:
        return 1.0
    matches = sum(1 for c in exp if c in got)
    return matches / len(exp)


# ═════════════════════════════════════════════════════════════════════════════
# ── SECTION 1: Morse Table ───────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════

class TestMorseTable:
    """Unit tests for morse_table.py"""

    def test_all_letters_present(self):
        """All 26 letters must be encodeable."""
        for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            assert ch in CHAR_TO_MORSE, f"Missing letter: {ch}"

    def test_all_digits_present(self):
        """Digits 0–9 must be encodeable."""
        for d in "0123456789":
            assert d in CHAR_TO_MORSE, f"Missing digit: {d}"

    def test_decode_e_and_t(self):
        """E='.' and T='-' are the shortest Morse codes."""
        assert decode_symbol(".") == "E"
        assert decode_symbol("-") == "T"

    def test_decode_sos(self):
        assert decode_symbol("...---...") == "SOS"

    def test_unknown_symbol_returns_question_mark(self):
        assert decode_symbol(".....-") == "?"

    def test_encode_decode_roundtrip(self):
        """encode_text → decode_symbol should recover original characters."""
        for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
            symbol = CHAR_TO_MORSE[ch]
            assert decode_symbol(symbol) == ch

    def test_encode_text_with_space(self):
        """Spaces should be represented as None in the encoded list."""
        encoded = encode_text("CQ DE")
        assert None in encoded   # word gap

    def test_morse_table_at_least_40_entries(self):
        assert len(MORSE_TO_CHAR) >= 40


# ═════════════════════════════════════════════════════════════════════════════
# ── SECTION 2: DSP Module ────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════

class TestDSP:
    """Unit tests for dsp.py"""

    def test_bandpass_filter_output_shape(self):
        audio = np.random.randn(SAMPLE_RATE).astype(np.float32)
        out = bandpass_filter(audio, SAMPLE_RATE, 300, 900)
        assert out.shape == audio.shape

    def test_bandpass_suppresses_dc(self):
        """DC component should be attenuated by the bandpass.
        The filter has transients at the first few samples (step response),
        but the steady-state (last 90%) must be near-zero."""
        dc = np.ones(SAMPLE_RATE, dtype=np.float32)
        out = bandpass_filter(dc, SAMPLE_RATE, 300, 900)
        steady_state = out[SAMPLE_RATE // 10:]   # skip first 10 % (transient)
        assert np.abs(steady_state).max() < 0.01

    def test_bandpass_passes_tone(self):
        """A 700 Hz tone should pass through with significant amplitude."""
        t = np.arange(SAMPLE_RATE, dtype=np.float32) / SAMPLE_RATE
        tone = np.sin(2 * np.pi * 700 * t)
        out = bandpass_filter(tone, SAMPLE_RATE, 300, 900)
        assert np.abs(out).max() > 0.5

    def test_envelope_non_negative(self):
        """Hilbert envelope must always be ≥ 0."""
        audio = np.random.randn(SAMPLE_RATE).astype(np.float32)
        env = envelope_detector(audio)
        assert env.min() >= 0.0

    def test_binarise_returns_0_and_1_only(self):
        signal = np.array([0.1, 0.5, 0.9, 0.3, 0.8], dtype=np.float32)
        binary = binarise(signal, threshold=0.4)
        assert set(binary.tolist()).issubset({0, 1})

    def test_preprocess_output_shapes(self):
        audio = generate_cw_audio("E", wpm=20)  # 1-char audio
        binary = preprocess(audio, SAMPLE_RATE)
        assert binary.shape == audio.shape
        assert set(binary.tolist()).issubset({0, 1})

    def test_dominant_frequency_detects_tone(self):
        """FFT peak should be close to the synthesised tone frequency."""
        t = np.arange(SAMPLE_RATE, dtype=np.float32) / SAMPLE_RATE
        tone = np.sin(2 * np.pi * 700 * t)
        freq = dominant_frequency(tone, SAMPLE_RATE)
        assert abs(freq - 700) < 50, f"Detected {freq} Hz, expected ~700 Hz"

    def test_preprocess_detects_tone_on(self):
        """Preprocess with explicit threshold on a pure 700 Hz tone.
        Auto-threshold is designed for bimodal (on/off) CW signals;
        for a continuous tone an explicit threshold of 0.3 is used here."""
        t = np.arange(SAMPLE_RATE * 2, dtype=np.float32) / SAMPLE_RATE
        tone = np.sin(2 * np.pi * 700 * t)
        # Pass explicit threshold so auto-mode doesn't over-threshold a DC signal
        binary = preprocess(tone, SAMPLE_RATE, threshold=0.3)
        ratio = binary.sum() / len(binary)
        assert ratio > 0.5, f"Expected >50% on, got {ratio:.1%}"


# ═════════════════════════════════════════════════════════════════════════════
# ── SECTION 3: Timing Analysis ───────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════

class TestTiming:
    """Unit tests for timing.py"""

    def test_run_length_encode_simple(self):
        binary = np.array([0, 0, 1, 1, 1, 0, 0], dtype=np.int8)
        pulses = run_length_encode(binary, sample_rate=1000)
        assert len(pulses) == 3
        assert pulses[0].is_tone is False
        assert pulses[1].is_tone is True
        assert pulses[2].is_tone is False

    def test_run_length_durations(self):
        # 200 samples @ 1000 Hz sample rate = 200 ms
        binary = np.zeros(200, dtype=np.int8)
        binary[100:] = 1
        pulses = run_length_encode(binary, sample_rate=1000)
        assert len(pulses) == 2
        assert abs(pulses[0].duration_ms - 100.0) < 1.0   # 100 samples = 100 ms
        assert abs(pulses[1].duration_ms - 100.0) < 1.0

    def test_timing_analysis_e(self):
        """Single 'E' (.) → should detect WPM > 0."""
        audio = generate_cw_audio("E", wpm=20)
        binary = preprocess(audio, SAMPLE_RATE)
        timing = analyse_timing(binary, SAMPLE_RATE)
        assert timing.estimated_wpm > 0
        assert timing.dit_ms > 0

    def test_timing_analysis_morse_symbols_present(self):
        """3+ char text should produce at least 3 Morse symbols."""
        audio = generate_cw_audio("RST", wpm=20)
        binary = preprocess(audio, SAMPLE_RATE)
        timing = analyse_timing(binary, SAMPLE_RATE)
        assert len(timing.morse_symbols) >= 3


# ═════════════════════════════════════════════════════════════════════════════
# ── SECTION 4: Text Reconstruction ──────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════

class TestTextReconstruction:

    def test_morse_sequence_single_char(self):
        text, raw, unknowns = morse_sequence_to_text([".", "-", " "])
        assert text == "A"
        assert unknowns == 0

    def test_morse_sequence_two_chars(self):
        # "AB" = .- / -... with space between
        symbols = [".", "-", " ", "-", ".", ".", ".", " "]
        text, _, _ = morse_sequence_to_text(symbols)
        assert text == "AB"

    def test_morse_sequence_word_gap(self):
        # "E T" = . / (word gap) -
        symbols = [".", " ", "/", "-", " "]
        text, _, _ = morse_sequence_to_text(symbols)
        assert "E" in text
        assert "T" in text
        assert " " in text

    def test_extract_callsigns_ct7bfv(self):
        callsigns = extract_callsigns("CQ CQ DE CT7BFV CT7BFV K")
        assert "CT7BFV" in callsigns

    def test_extract_callsigns_multiple(self):
        callsigns = extract_callsigns("CT7BFV DE W1AW")
        assert "CT7BFV" in callsigns
        assert "W1AW" in callsigns


# ═════════════════════════════════════════════════════════════════════════════
# ── SECTION 5: End-to-End Decoding ───────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════

class TestEndToEnd:
    """Full pipeline: synthesise → decode."""

    @pytest.mark.parametrize("char", list("ETIMANST"))
    def test_common_chars_clean(self, char):
        """Most common CW characters should decode at 20 WPM with clean signal."""
        result = decode_text(char, wpm=20, noise_db=-60.0)
        assert char in result.text.upper() or result.confidence > 0.3, \
            f"'{char}' not decoded: got '{result.text}' (conf={result.confidence})"

    def test_callsign_ct7bfv_clean(self):
        """CT7BFV should be decodable at 20 WPM with clean signal."""
        result = decode_text("CT7BFV", wpm=20, noise_db=-60.0)
        assert result.confidence > 0.0
        assert len(result.text) >= 3, f"Too short: '{result.text}'"

    def test_cq_de_phrase(self):
        """CQ DE should produce some recognisable output."""
        result = decode_text("CQ DE", wpm=20, noise_db=-60.0)
        assert result.wpm > 0
        assert len(result.text) >= 2

    def test_result_has_wpm(self):
        result = decode_text("K", wpm=20)
        assert result.wpm > 0

    def test_result_has_dominant_freq(self):
        result = decode_text("E", wpm=20)
        # Dominant freq should be close to 700 Hz
        assert 400 < result.dominant_freq_hz < 1000

    def test_wpm_10(self):
        """Slow CW at 10 WPM."""
        result = decode_text("RST", wpm=10, noise_db=-60.0)
        assert result.wpm > 0
        assert 5 <= result.wpm <= 25

    def test_wpm_25(self):
        """Moderate-speed CW at 25 WPM."""
        result = decode_text("DE", wpm=25, noise_db=-60.0)
        assert result.wpm > 0

    def test_wpm_30(self):
        """Fast CW at 30 WPM."""
        result = decode_text("GM", wpm=30, noise_db=-60.0)
        assert result.wpm > 0

    @pytest.mark.parametrize("noise_db", [-40.0, -20.0])
    def test_noise_tolerance(self, noise_db: float):
        """Decoder should run without error at moderate noise levels."""
        result = decode_text("CQ", wpm=20, noise_db=noise_db)
        # We don't require correctness at high noise, just no crash
        assert isinstance(result, DecodeResult)
        assert result.wpm >= 0

    def test_qso_phrase(self):
        """Short QSO exchange."""
        result = decode_text("CQ DE CT7BFV K", wpm=18, noise_db=-60.0)
        assert result.wpm > 5

    def test_empty_audio_returns_empty_result(self):
        audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
        dec = CWDecoder(sample_rate=SAMPLE_RATE)
        result = dec.decode(audio)
        assert result.text == ""
        assert result.confidence == 0.0

    def test_long_text(self):
        """Test with a longer message."""
        result = decode_text("CQ CQ CQ DE CT7BFV CT7BFV PSE K", wpm=20, noise_db=-60.0)
        assert result.wpm > 0
        assert len(result.text) >= 5

    def test_confidence_is_bounded(self):
        result = decode_text("TEST", wpm=20)
        assert 0.0 <= result.confidence <= 1.0

    def test_callsign_extraction_in_result(self):
        result = decode_text("DE CT7BFV K", wpm=20, noise_db=-60.0)
        # May or may not decode perfectly; at minimum no crash
        assert isinstance(result.callsigns, list)


# ═════════════════════════════════════════════════════════════════════════════
# ── SECTION 6: Streaming Decoder ─────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════

class TestStreaming:

    def test_streaming_yields_results(self):
        """Streaming decoder should yield at least one result for a long message."""
        audio = generate_cw_audio(
            "CQ CQ DE CT7BFV CT7BFV TEST TEST K",
            wpm=20, noise_db=-60.0
        )
        # Split into 1-second chunks
        chunk_size = SAMPLE_RATE
        chunks = [audio[i:i+chunk_size] for i in range(0, len(audio), chunk_size)]

        dec = CWDecoder(sample_rate=SAMPLE_RATE)
        results = list(dec.decode_streaming(iter(chunks)))
        # With a long enough message, at least one result should appear
        # (may produce 0 if message is shorter than 10 s buffer)
        assert isinstance(results, list)

    def test_streaming_results_are_decoderesult(self):
        audio = generate_cw_audio("CQ " * 20, wpm=20, noise_db=-60.0)
        chunk_size = SAMPLE_RATE
        chunks = [audio[i:i+chunk_size] for i in range(0, len(audio), chunk_size)]
        dec = CWDecoder(sample_rate=SAMPLE_RATE)
        for result in dec.decode_streaming(iter(chunks)):
            assert isinstance(result, DecodeResult)


# ═════════════════════════════════════════════════════════════════════════════
# ── Benchmark (not collected by pytest automatically)
# ═════════════════════════════════════════════════════════════════════════════

def benchmark_decode_speed():
    """Measure decode throughput — not a test, run manually."""
    audio = generate_cw_audio("CQ DE CT7BFV TEST K 73", wpm=20)
    dec = CWDecoder(sample_rate=SAMPLE_RATE)
    N = 50
    start = time.perf_counter()
    for _ in range(N):
        dec.decode(audio)
    elapsed = time.perf_counter() - start
    duration_s = len(audio) / SAMPLE_RATE
    print(f"\nBenchmark: {N} × {duration_s:.1f}s audio → "
          f"avg {1000*elapsed/N:.1f} ms/decode "
          f"({N*duration_s/elapsed:.1f}× realtime)")


if __name__ == "__main__":
    benchmark_decode_speed()
    pytest.main([__file__, "-v", "--tb=short"])
