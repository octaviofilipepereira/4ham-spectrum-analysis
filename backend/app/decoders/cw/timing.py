# © 2026 CT7BFV — CW Timing Analysis
"""
Timing analysis for CW (Morse code) decoding.

Converts a binary (on/off) signal into a sequence of Morse symbols
by measuring pulse durations and classifying them as dits, dahs,
character gaps, and word gaps.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Pulse:
    """A single tone-on or tone-off interval."""
    is_tone: bool            # True = tone on, False = silence
    duration_ms: float       # Duration in milliseconds
    symbol: str = ""         # Assigned after classification: '.', '-', ' ', '/', ''


@dataclass
class TimingResult:
    """Output of timing analysis."""
    pulses: list[Pulse] = field(default_factory=list)
    estimated_wpm: float = 0.0
    dit_ms: float = 0.0      # Estimated dit (dot) duration
    dah_ms: float = 0.0      # Estimated dah (dash) duration
    morse_symbols: list[str] = field(default_factory=list)  # '.' '-' ' ' '/'


# ─────────────────────────────────────────────────────────────────────────────
# Run-length encoding
# ─────────────────────────────────────────────────────────────────────────────

def run_length_encode(binary: "np.ndarray", sample_rate: int) -> list[Pulse]:
    """
    Convert a binary signal (0/1 int8) into a list of Pulses with durations.

    Each run of identical samples becomes one Pulse.
    """
    if len(binary) == 0:
        return []

    pulses: list[Pulse] = []
    current_val = int(binary[0])
    run_start = 0

    for i in range(1, len(binary)):
        val = int(binary[i])
        if val != current_val:
            duration_ms = (i - run_start) / sample_rate * 1000.0
            pulses.append(Pulse(is_tone=(current_val == 1), duration_ms=duration_ms))
            current_val = val
            run_start = i

    # Last run
    duration_ms = (len(binary) - run_start) / sample_rate * 1000.0
    pulses.append(Pulse(is_tone=(current_val == 1), duration_ms=duration_ms))

    return pulses


# ─────────────────────────────────────────────────────────────────────────────
# WPM / dit estimation
# ─────────────────────────────────────────────────────────────────────────────

def estimate_dit_ms(tone_pulses: list[Pulse]) -> float:
    """
    Estimate dit duration from tone-on pulses.

    Uses the PARIS standard: 1 WPM = 1200 ms/dit.
    We cluster tone durations and take the smaller cluster as dits.
    Falls back to the minimum tone duration if clustering fails.
    """
    if not tone_pulses:
        return 60.0   # default: ~20 WPM

    durations = sorted(p.duration_ms for p in tone_pulses)

    if len(durations) == 1:
        return durations[0]

    # Median of shortest 50 % as dit estimate (robust to long dahs skewing mean)
    half = max(1, len(durations) // 2)
    return float(sum(durations[:half]) / half)


def wpm_from_dit(dit_ms: float) -> float:
    """PARIS standard: WPM = 1200 / dit_ms."""
    if dit_ms <= 0:
        return 0.0
    return 1200.0 / dit_ms


# ─────────────────────────────────────────────────────────────────────────────
# Pulse classifier
# ─────────────────────────────────────────────────────────────────────────────

def classify_pulses(pulses: list[Pulse], dit_ms: float) -> list[Pulse]:
    """
    Assign Morse symbol to each pulse using dit_ms as reference:

    Tone-on:
      ≤ 2× dit  → dit  '.'
      > 2× dit  → dah  '-'

    Tone-off (silence):
      ≤ 2× dit  → intra-character gap  ''
      ≤ 5× dit  → inter-character gap  ' '
      > 5× dit  → word gap             '/'

    The thresholds intentionally have some tolerance to handle
    timing jitter, especially at higher WPM.
    """
    dah_threshold = dit_ms * 2.0
    char_gap_threshold = dit_ms * 2.0
    word_gap_threshold = dit_ms * 5.0

    for p in pulses:
        if p.is_tone:
            p.symbol = "." if p.duration_ms <= dah_threshold else "-"
        else:
            if p.duration_ms <= char_gap_threshold:
                p.symbol = ""     # within-character gap, ignore
            elif p.duration_ms <= word_gap_threshold:
                p.symbol = " "    # between characters
            else:
                p.symbol = "/"    # between words

    return pulses


# ─────────────────────────────────────────────────────────────────────────────
# Build Morse symbols sequence
# ─────────────────────────────────────────────────────────────────────────────

def build_morse_sequence(pulses: list[Pulse]) -> list[str]:
    """
    Flatten classified pulses into a list of Morse symbols.
    Returns a list of '.', '-', ' ', '/' strings.
    """
    return [p.symbol for p in pulses if p.symbol != ""]


# ─────────────────────────────────────────────────────────────────────────────
# Top-level entry point
# ─────────────────────────────────────────────────────────────────────────────

def analyse_timing(binary: "np.ndarray", sample_rate: int) -> TimingResult:
    """
    Full timing analysis pipeline.

    Args:
        binary:      int8 array of 0/1 values from dsp.preprocess().
        sample_rate: Hz (must match what produced the binary array).

    Returns:
        TimingResult with classified pulses, WPM estimate, and symbol list.
    """
    pulses = run_length_encode(binary, sample_rate)

    tone_pulses = [p for p in pulses if p.is_tone]
    if not tone_pulses:
        return TimingResult()

    dit_ms = estimate_dit_ms(tone_pulses)
    dah_ms = dit_ms * 3.0
    wpm    = wpm_from_dit(dit_ms)

    classified = classify_pulses(pulses, dit_ms)
    morse_seq  = build_morse_sequence(classified)

    return TimingResult(
        pulses=classified,
        estimated_wpm=wpm,
        dit_ms=dit_ms,
        dah_ms=dah_ms,
        morse_symbols=morse_seq,
    )
