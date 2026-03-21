# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

"""SSB Automatic Speech Recognition (ASR) module.

Accumulates demodulated USB/LSB audio from IQ frames captured during the
SSB hold period and transcribes them with OpenAI Whisper.

Installation (optional):
    pip install openai-whisper

If whisper is not installed the module degrades gracefully: accumulation and
transcription are no-ops and the spectral-proof fallback is used instead.
"""

import math
import threading
import time as _time_module
from typing import Dict, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Optional whisper import
# ---------------------------------------------------------------------------
_whisper = None
_whisper_unavailable_reason: str = ""

try:
    import whisper as _whisper  # type: ignore[import]
except ImportError as _exc:
    _whisper_unavailable_reason = str(_exc)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_TARGET_SR = 16_000          # Hz – Whisper's expected sample rate
_MAX_BUF_SAMPLES = _TARGET_SR * 20   # 20 s max per bucket
_MIN_BUF_SAMPLES = _TARGET_SR * 3    # need at least 3 s before transcribing
_FREQ_LSB_THRESHOLD_HZ = 10_000_000  # below 10 MHz → LSB convention


# ---------------------------------------------------------------------------
# Audio demodulation
# ---------------------------------------------------------------------------

def _demodulate_ssb(iq: np.ndarray, sample_rate: int, offset_hz: float,
                    frequency_hz: int) -> np.ndarray:
    """Demodulate a USB or LSB SSB signal from complex IQ to float32 audio.

    Steps:
      1. Frequency-shift the IQ block so the signal carrier lands at DC.
      2. For LSB (typically <10 MHz): conjugate to mirror spectrum back to positive.
      3. Low-pass filter at 3200 Hz (SSB audio passband).
      4. Take real (I) component.
      5. Resample to 16 kHz for Whisper.
    """
    from scipy.signal import butter, sosfilt, resample_poly  # lazy import

    n = np.arange(len(iq), dtype=np.float64)
    iq_shifted = iq * np.exp(-2j * np.pi * offset_hz / sample_rate * n)

    # LSB: audio is in the negative-frequency sideband; conjugate to flip
    if frequency_hz < _FREQ_LSB_THRESHOLD_HZ:
        iq_shifted = np.conj(iq_shifted)

    # Low-pass filter to keep only the audio band
    nyq = sample_rate / 2.0
    sos = butter(6, min(3200.0 / nyq, 0.999), btype="low", output="sos")
    audio = sosfilt(sos, np.real(iq_shifted)).astype(np.float32)

    # Resample from SDR sample rate to 16 kHz
    gcd = math.gcd(int(sample_rate), _TARGET_SR)
    up = _TARGET_SR // gcd
    down = int(sample_rate) // gcd
    audio_16k = resample_poly(audio, up, down).astype(np.float32)

    return audio_16k


# ---------------------------------------------------------------------------
# ASR engine
# ---------------------------------------------------------------------------

class SsbAsrEngine:
    """Per-frequency audio accumulator and Whisper transcription engine."""

    def __init__(self, model_size: str = "tiny"):
        self._model_size = model_size
        self._model = None
        self._model_lock = threading.Lock()
        self._buf_lock = threading.Lock()
        self._buffers: Dict[int, np.ndarray] = {}
        self._transcripts: Dict[int, str] = {}

    @property
    def is_available(self) -> bool:
        return _whisper is not None

    def _ensure_model(self) -> bool:
        """Lazy-load model under lock. Returns True if model is ready."""
        if self._model is not None:
            return True
        if _whisper is None:
            return False
        try:
            self._model = _whisper.load_model(self._model_size)
            return self._model is not None
        except Exception:
            return False

    def feed_iq(
        self,
        bucket_key: int,
        iq: np.ndarray,
        sample_rate: int,
        offset_hz: float,
        frequency_hz: int,
    ) -> None:
        """Demodulate *iq* and append resulting audio to the bucket buffer."""
        if not self.is_available or iq is None or len(iq) == 0:
            return
        try:
            audio = _demodulate_ssb(iq, sample_rate, float(offset_hz), frequency_hz)
            if len(audio) == 0:
                return
            with self._buf_lock:
                buf = self._buffers.get(bucket_key)
                if buf is None:
                    buf = audio
                else:
                    buf = np.concatenate([buf, audio])
                # Rolling window: keep only the most recent _MAX_BUF_SAMPLES
                if len(buf) > _MAX_BUF_SAMPLES:
                    buf = buf[-_MAX_BUF_SAMPLES:]
                self._buffers[bucket_key] = buf
        except Exception:
            pass

    def transcribe_bucket(self, bucket_key: int) -> str:
        """Blocking: transcribe the accumulated audio for *bucket_key*.

        Should be called via ``asyncio.run_in_executor`` so it does not
        stall the event loop.  Clears the buffer after transcription and
        caches the result for retrieval via ``get_last_transcript``.
        """
        if not self.is_available:
            return ""

        # Snapshot + clear buffer
        with self._buf_lock:
            buf = self._buffers.pop(bucket_key, None)

        if buf is None or len(buf) < _MIN_BUF_SAMPLES:
            return ""

        try:
            # Normalise audio to ±0.95
            peak = float(np.max(np.abs(buf)))
            if peak > 1e-6:
                buf = (buf / peak * 0.95).astype(np.float32)

            with self._model_lock:
                if not self._ensure_model():
                    return ""
                result = self._model.transcribe(
                    buf,
                    fp16=False,
                    language=None,          # auto-detect language
                    condition_on_previous_text=False,
                )

            text = str(result.get("text") or "").strip()
            if text:
                self._transcripts[bucket_key] = text
            return text
        except Exception:
            return ""

    def get_last_transcript(self, bucket_key: int) -> str:
        """Return the most recently computed transcript without blocking."""
        return self._transcripts.get(bucket_key, "")

    def clear_bucket(self, bucket_key: int) -> None:
        with self._buf_lock:
            self._buffers.pop(bucket_key, None)
        self._transcripts.pop(bucket_key, None)


# ---------------------------------------------------------------------------
# Module-level singleton and convenience helpers
# ---------------------------------------------------------------------------

_engine = SsbAsrEngine(model_size="tiny")


# ---------------------------------------------------------------------------
# Runtime enable / disable
# ---------------------------------------------------------------------------

_asr_enabled: bool = True


def set_asr_enabled(value: bool) -> None:
    """Enable or disable ASR at runtime (called by the settings API)."""
    global _asr_enabled
    _asr_enabled = bool(value)


def is_asr_enabled() -> bool:
    return _asr_enabled


# ---------------------------------------------------------------------------
# Module-level convenience helpers
# ---------------------------------------------------------------------------

def feed_iq_ssb(
    bucket_key: int,
    iq: np.ndarray,
    sample_rate: int,
    offset_hz: float,
    frequency_hz: int,
) -> None:
    if not _asr_enabled:
        return
    _engine.feed_iq(bucket_key, iq, sample_rate, offset_hz, frequency_hz)


def transcribe_bucket_ssb(bucket_key: int) -> str:
    """Blocking transcription — call via run_in_executor from async code."""
    if not _asr_enabled:
        return ""
    return _engine.transcribe_bucket(bucket_key)


def get_last_transcript_ssb(bucket_key: int) -> str:
    """Non-blocking: return last cached transcript for bucket_key."""
    return _engine.get_last_transcript(bucket_key)


def is_ssb_asr_available() -> bool:
    return _engine.is_available


# ---------------------------------------------------------------------------
# Background (fire-and-forget) transcription helper
# ---------------------------------------------------------------------------

_last_transcribed_at: Dict[int, float] = {}
_TRANSCRIBE_MIN_INTERVAL_S: float = 10.0  # seconds between transcription attempts per bucket


def maybe_transcribe_ssb(bucket_key: int) -> bool:
    """Schedule a background Whisper transcription if the buffer is ready.

    Non-blocking: submits work to the thread-pool executor and returns
    immediately.  The transcript is cached inside the engine and readable
    via ``get_last_transcript_ssb()`` once the thread finishes.

    Returns True if a transcription was scheduled, False otherwise.
    """
    import asyncio
    if not _asr_enabled or not _engine.is_available:
        return False
    now = _time_module.time()
    last = _last_transcribed_at.get(bucket_key, 0.0)
    if (now - last) < _TRANSCRIBE_MIN_INTERVAL_S:
        return False
    # Claim the slot before checking buffer to avoid double-scheduling
    _last_transcribed_at[bucket_key] = now
    buf = _engine._buffers.get(bucket_key)
    if buf is None or len(buf) < _MIN_BUF_SAMPLES:
        # Not enough audio yet; release the slot
        _last_transcribed_at.pop(bucket_key, None)
        return False
    try:
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, transcribe_bucket_ssb, bucket_key)
        return True
    except Exception:
        return False
