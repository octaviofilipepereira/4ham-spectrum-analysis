# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

"""
CW Sweep Decoder
================
Parks the SDR at consecutive positions across the CW segment of a band,
collecting a fixed audio window at each position and attempting to decode
any CW transmissions found.

Sweep cycle per position:
  1. scan_park(pos_hz)         — freeze SDR on this centre frequency
  2. iq_flush()                — discard stale samples from the previous position
  3. sleep settle_ms           — wait for SDR PLL to re-lock
  4. collect dwell_s of IQ     — gather a clean audio window
  5. audio = np.real(iq)       — USB demodulation: CW carrier preserved at offset Hz
  6. resample → target_sr      — normalise for CWDecoder (8 kHz)
  7. CWDecoder.decode(audio)   — attempt Morse decode
  8. emit events               — report callsigns with absolute RF frequency

On reaching band_end_hz, the cycle wraps back to band_start_hz.
scan_unpark() is called on stop() so the scan engine resumes sweeping.

Position geometry (example: 20m CW, step=6500 Hz, settle=100 ms, dwell=5 s):
  positions: 14000, 14006.5, 14013, 14019.5, 14026, 14032.5, 14039, 14045.5,
             14052, 14058.5, 14065, 14070  kHz  →  12 positions
  cycle time: 12 × (0.1 + 5.0) ≈ 61 s
  coverage per position: ±3.8 kHz  (limited by 8 kHz target sample rate Nyquist)
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, List, Optional

import numpy as np

_logger = logging.getLogger(__name__)

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CWSweepDecoder:
    """
    Band-sweep CW decoder.

    Parks the SDR sequentially at positions from band_start_hz to band_end_hz
    separated by step_hz.  At each position, collects dwell_s seconds of IQ,
    demodulates via np.real() (USB), resamples, and attempts CW decode.

    Parameters
    ----------
    band_start_hz : int
        First centre frequency of the sweep (Hz).
    band_end_hz : int
        Last centre frequency of the sweep (Hz).
    step_hz : int
        Frequency step between consecutive positions (default 6500 Hz).
        Must be ≤ usable SDR bandwidth so adjacent positions overlap slightly.
    dwell_s : float
        Seconds to spend collecting IQ at each position (default 5.0 s).
    settle_ms : int
        Milliseconds to wait after park() before starting IQ collection,
        allowing the SDR PLL to re-lock (default 100 ms).
    iq_provider : callable
        No-argument callable returning a complex64 ndarray chunk or None.
    iq_flush : callable
        No-argument callable that drains stale samples from the IQ queue.
    sample_rate_provider : callable
        No-argument callable returning the current SDR sample rate (Hz).
    frequency_provider : callable
        No-argument callable returning the current SDR centre frequency (Hz).
    scan_park : callable(int)
        Callback to freeze the scan engine on a specific frequency.
    scan_unpark : callable()
        Callback to resume normal scan engine sweeping.
    on_event : callable(dict)
        Callback invoked for each decoded CW event.
    logger : callable(str)
        Optional logging callback.
    target_sample_rate : int
        Audio sample rate fed to CWDecoder (default 8000 Hz).
    min_confidence : float
        Minimum CWDecoder confidence to emit events (0.0–1.0, default 0.3).
    """

    def __init__(
        self,
        band_start_hz: int,
        band_end_hz: int,
        step_hz: int = 6500,
        dwell_s: float = 5.0,
        settle_ms: int = 100,
        iq_provider: Optional[Callable[[], Optional[np.ndarray]]] = None,
        iq_flush: Optional[Callable[[], None]] = None,
        sample_rate_provider: Optional[Callable[[], int]] = None,
        frequency_provider: Optional[Callable[[], int]] = None,
        scan_park: Optional[Callable[[int], None]] = None,
        scan_unpark: Optional[Callable[[], None]] = None,
        on_event: Optional[Callable[[dict], None]] = None,
        logger: Optional[Callable[[str], None]] = None,
        target_sample_rate: int = 8000,
        min_confidence: float = 0.3,
    ):
        self.band_start_hz = int(band_start_hz)
        self.band_end_hz = int(band_end_hz)
        self.step_hz = max(1000, int(step_hz))
        self.dwell_s = max(0.05, float(dwell_s))
        self.settle_ms = max(5, int(settle_ms))
        self.iq_provider = iq_provider
        self.iq_flush = iq_flush
        self.sample_rate_provider = sample_rate_provider
        self.frequency_provider = frequency_provider
        self.scan_park = scan_park
        self.scan_unpark = scan_unpark
        self.on_event = on_event
        self.logger = logger
        self.target_sample_rate = max(4000, int(target_sample_rate))
        self.min_confidence = max(0.0, min(1.0, float(min_confidence)))

        from .cw.decoder import CWDecoder
        self._decoder = CWDecoder(
            sample_rate=self.target_sample_rate,
            min_snr_db=0.0,
            max_wpm=120.0,
            min_audio_duration=2.0,
        )

        # Runtime state
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._started_at: Optional[str] = None
        self._stopped_at: Optional[str] = None
        self._last_heartbeat_at: Optional[str] = None
        self._last_error: Optional[str] = None

        # Statistics
        self._current_position_hz: int = 0
        self._position_index: int = 0
        self._cycle_count: int = 0
        self._decode_attempts: int = 0
        self._events_emitted: int = 0
        self._callsigns_detected: int = 0
        self._last_decode_text: Optional[str] = None
        self._last_wpm: float = 0.0
        self._last_confidence: float = 0.0
        self._last_event_at: Optional[str] = None

    # ──────────────────────────────────────────────────────────────
    # Public interface
    # ──────────────────────────────────────────────────────────────

    async def start(self) -> bool:
        """Start the sweep loop. Returns False if already running."""
        if self._running:
            return False
        self._running = True
        self._started_at = _utc_now_iso()
        self._stopped_at = None
        self._task = asyncio.create_task(self._run())
        positions = self._build_positions()
        self._log(
            f"cw_sweep_started band={self.band_start_hz}-{self.band_end_hz}Hz "
            f"step={self.step_hz}Hz positions={len(positions)} "
            f"dwell={self.dwell_s}s settle={self.settle_ms}ms"
        )
        return True

    async def stop(self) -> bool:
        """Stop the sweep and release the scan engine park."""
        if not self._running:
            return False
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # Always unpark so the scan engine can resume
        if self.scan_unpark:
            try:
                self.scan_unpark()
            except Exception:
                pass
        self._stopped_at = _utc_now_iso()
        self._log("cw_sweep_stopped")
        return True

    def snapshot(self) -> dict:
        """Return current state as a serialisable dict."""
        return {
            "enabled": True,
            "running": self._running,
            "mode": "sweep",
            "band_start_hz": self.band_start_hz,
            "band_end_hz": self.band_end_hz,
            "step_hz": self.step_hz,
            "dwell_s": self.dwell_s,
            "settle_ms": self.settle_ms,
            "target_sample_rate": self.target_sample_rate,
            "min_confidence": self.min_confidence,
            "current_position_hz": self._current_position_hz,
            "position_index": self._position_index,
            "cycle_count": self._cycle_count,
            "decode_attempts": self._decode_attempts,
            "events_emitted": self._events_emitted,
            "callsigns_detected": self._callsigns_detected,
            "last_event_at": self._last_event_at,
            "last_decode_text": self._last_decode_text,
            "last_wpm": self._last_wpm,
            "last_confidence": self._last_confidence,
            "last_error": self._last_error,
            "started_at": self._started_at,
            "stopped_at": self._stopped_at,
            "last_heartbeat_at": self._last_heartbeat_at,
        }

    # ──────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────

    def _log(self, msg: str, level: str = "info") -> None:
        # Always publish to in-memory log (accessible via /api/logs)
        if self.logger:
            try:
                self.logger(msg)
            except Exception:
                pass
        # Also write to the Python file logger
        getattr(_logger, level, _logger.info)(msg)

    def _build_positions(self) -> List[int]:
        """Generate the ordered list of centre frequencies to sweep."""
        positions: List[int] = []
        freq = self.band_start_hz
        while freq <= self.band_end_hz:
            positions.append(freq)
            freq += self.step_hz
        # Ensure band_end_hz is always the final position
        if positions and positions[-1] < self.band_end_hz:
            positions.append(self.band_end_hz)
        return positions

    async def _collect_window(self, source_sample_rate: int) -> Optional[np.ndarray]:
        """
        Collect dwell_s seconds of IQ, demodulate with np.real(), and
        resample to target_sample_rate.

        Returns None if the decoder was stopped before the window was filled.
        """
        target_samples = int(self.dwell_s * self.target_sample_rate)
        buffer = np.array([], dtype=np.float32)

        while len(buffer) < target_samples and self._running:
            # Call the provider directly (it is a non-blocking sync function).
            # Yield to the event loop between empty polls so other coroutines
            # can run while we wait for fresh IQ chunks.
            iq = self.iq_provider()
            if iq is None or len(iq) == 0:
                await asyncio.sleep(0.005)
                continue

            # USB/SSB demodulation: keep I component.
            # CW carrier at (pos_hz + f_offset) Hz produces audio tone at f_offset Hz.
            audio = np.real(iq).astype(np.float32)

            if source_sample_rate != self.target_sample_rate:
                from scipy.signal import resample_poly
                gcd = int(np.gcd(source_sample_rate, self.target_sample_rate))
                up = self.target_sample_rate // gcd
                down = source_sample_rate // gcd
                audio = resample_poly(audio, up, down).astype(np.float32)

            buffer = np.concatenate([buffer, audio])

        if len(buffer) < target_samples:
            return None  # stopped before window was full
        return buffer[:target_samples]

    # ──────────────────────────────────────────────────────────────
    # Main loop
    # ──────────────────────────────────────────────────────────────

    async def _run(self) -> None:
        try:
            positions = self._build_positions()
            if not positions:
                self._log("cw_sweep_no_positions — band_end_hz <= band_start_hz")
                self._running = False
                return

            pos_idx = 0

            while self._running:
                pos_hz = positions[pos_idx]
                self._position_index = pos_idx
                self._current_position_hz = pos_hz
                self._last_heartbeat_at = _utc_now_iso()

                # ── 1. Park SDR on this position ──────────────────────────
                if self.scan_park:
                    try:
                        self.scan_park(pos_hz)
                    except Exception as exc:
                        self._log(f"cw_sweep_park_error pos={pos_hz} {exc}")

                # ── 2. Flush IQ queue (discard stale samples) ─────────────
                if self.iq_flush:
                    try:
                        self.iq_flush()
                    except Exception:
                        pass

                # ── 3. Wait for SDR PLL settle ────────────────────────────
                await asyncio.sleep(self.settle_ms / 1000.0)

                # ── 4. Get current sample rate ────────────────────────────
                source_sample_rate = (
                    self.sample_rate_provider() if self.sample_rate_provider else 48000
                )
                if source_sample_rate <= 0:
                    self._log(f"cw_sweep_no_sample_rate pos={pos_hz}")
                    await asyncio.sleep(0.25)
                    pos_idx = (pos_idx + 1) % len(positions)
                    if pos_idx == 0:
                        self._cycle_count += 1
                    continue

                # ── 5. Collect audio window ───────────────────────────────
                audio = await self._collect_window(source_sample_rate)
                if audio is None:
                    # Decoder was stopped mid-collection
                    break

                # ── 6. Decode ─────────────────────────────────────────────
                self._decode_attempts += 1
                # Diagnostic: log audio statistics before decode
                audio_rms = float(np.sqrt(np.mean(audio ** 2))) if len(audio) > 0 else 0.0
                audio_peak = float(np.max(np.abs(audio))) if len(audio) > 0 else 0.0
                # Quick FFT for dominant frequency diagnostic
                _fft_mag = np.abs(np.fft.rfft(audio))
                _freqs = np.fft.rfftfreq(len(audio), d=1.0 / self.target_sample_rate)
                _mask = (_freqs >= 100) & (_freqs <= self.target_sample_rate / 2 - 200)
                _dom_hz = float(_freqs[_mask][np.argmax(_fft_mag[_mask])]) if _mask.any() else 0.0
                self._log(
                    f"cw_sweep_audio pos={pos_hz}Hz samples={len(audio)} "
                    f"rms={audio_rms:.6f} peak={audio_peak:.4f} dom_freq={_dom_hz:.0f}Hz "
                    f"sr={source_sample_rate}",
                    level="debug",
                )
                result = await asyncio.to_thread(self._decoder.decode, audio)

                self._last_decode_text = result.text
                self._last_wpm = result.wpm
                self._last_confidence = result.confidence

                self._log(
                    f"cw_sweep pos={pos_hz}Hz attempt={self._decode_attempts} "
                    f"tone={result.dominant_freq_hz:.0f}Hz "
                    f"wpm={result.wpm:.1f} conf={result.confidence:.2f} "
                    f"text={repr(result.text[:40])}",
                    level="info" if result.confidence > 0 else "debug",
                )

                # ── 7. Emit events ────────────────────────────────────────
                if result.callsigns and result.confidence >= self.min_confidence:
                    # Deduplicate: a single transmission often repeats the same
                    # callsign (e.g. "IK6LBT IK6LBT DE CT7BFV"). Emit once per
                    # unique callsign, preserving first-seen order.
                    unique_callsigns = list(dict.fromkeys(result.callsigns))
                    self._callsigns_detected += len(unique_callsigns)
                    # Absolute RF frequency: SDR centre + audio-domain tone offset
                    rf_freq_hz = pos_hz + int(result.dominant_freq_hz)
                    for callsign in unique_callsigns:
                        event = {
                            "timestamp": _utc_now_iso(),
                            "mode": "CW",
                            "callsign": callsign,
                            "frequency_hz": rf_freq_hz,
                            "snr_db": 0.0,
                            "dt_s": 0.0,
                            "df_hz": int(result.dominant_freq_hz),
                            "confidence": result.confidence,
                            "msg": result.text,
                            "raw": f"CW {result.wpm:.1f}wpm",
                            "source": "internal_cw",
                        }
                        if self.on_event:
                            try:
                                self.on_event(event)
                                self._events_emitted += 1
                                self._last_event_at = _utc_now_iso()
                            except Exception as exc:
                                self._log(f"cw_sweep_event_error {exc}")

                # ── 8. Advance to next position ───────────────────────────
                pos_idx = (pos_idx + 1) % len(positions)
                if pos_idx == 0:
                    self._cycle_count += 1
                    self._log(
                        f"cw_sweep_cycle_complete cycle={self._cycle_count} "
                        f"events_this_session={self._events_emitted}"
                    )

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._last_error = str(exc)
            self._running = False
            self._log(f"cw_sweep_failed {exc}")
