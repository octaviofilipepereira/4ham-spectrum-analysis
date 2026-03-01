# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# CW Decoder Session Manager

"""
CW Decoder Session Manager
===========================
Manages CW decoder lifecycle, audio collection, and event emission.
Similar to ExternalFtDecoder but for CW.
"""

import asyncio
from datetime import datetime, timezone
from typing import Callable, Optional
import numpy as np

from .cw.decoder import CWDecoder


def _utc_now_iso() -> str:
    """Return current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


class CWDecoderSession:
    """
    Session manager for CW decoder.
    
    Lifecycle:
    1. User clicks "CW" button in frontend
    2. API calls start() → creates asyncio task running _run()
    3. _run() loop:
       - Collects audio chunks from IQ provider
       - Processes with CWDecoder
       - Emits events via on_event callback
    4. User clicks another mode → API calls stop()
    """
    
    def __init__(
        self,
        iq_provider: Optional[Callable[[int], Optional[np.ndarray]]] = None,
        sample_rate_provider: Optional[Callable[[], int]] = None,
        frequency_provider: Optional[Callable[[], int]] = None,
        on_event: Optional[Callable[[dict], None]] = None,
        logger: Optional[Callable[[str], None]] = None,
        target_sample_rate: int = 8000,
        window_seconds: float = 5.0,
        overlap_seconds: float = 2.0,
        poll_interval_s: float = 0.25,
        min_confidence: float = 0.3,
    ):
        """
        Initialize CW decoder session.
        
        Args:
            iq_provider: Function that returns N IQ samples (complex64 numpy array)
            sample_rate_provider: Function that returns current SDR sample rate (Hz)
            frequency_provider: Function that returns current center frequency (Hz)
            on_event: Callback for decoded CW events (callsign detected)
            logger: Optional logging function
            target_sample_rate: Resample audio to this rate before decoding (Hz)
            window_seconds: Audio window size for each decode attempt (seconds)
            overlap_seconds: Overlap between consecutive windows (seconds)
            poll_interval_s: Polling interval when no IQ available (seconds)
            min_confidence: Minimum confidence to emit events (0.0-1.0)
        """
        self.iq_provider = iq_provider
        self.sample_rate_provider = sample_rate_provider
        self.frequency_provider = frequency_provider
        self.on_event = on_event
        self.logger = logger
        self.target_sample_rate = max(4000, int(target_sample_rate))
        self.window_seconds = max(1.0, float(window_seconds))
        self.overlap_seconds = max(0.0, float(overlap_seconds))
        self.poll_interval_s = max(0.05, float(poll_interval_s))
        self.min_confidence = max(0.0, min(1.0, float(min_confidence)))
        
        # CW decoder instance with quality validations enabled
        # Real-world signals are always 5+ seconds, so we can apply strict filtering
        self.decoder = CWDecoder(
            sample_rate=self.target_sample_rate,
            min_snr_db=3.0,      # Reject if SNR < 3 dB (pure noise)
            max_wpm=100.0,       # Reject if WPM > 100 (unrealistic)
            min_audio_duration=2.0,  # Only apply SNR check to signals >= 2s
        )
        
        # State
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._started_at: Optional[str] = None
        self._stopped_at: Optional[str] = None
        self._last_heartbeat_at: Optional[str] = None
        self._last_error: Optional[str] = None
        
        # Statistics
        self._decode_attempts = 0
        self._events_emitted = 0
        self._callsigns_detected = 0
        self._last_event_at: Optional[str] = None
        self._last_decode_text: Optional[str] = None
        self._last_wpm: float = 0.0
        self._last_confidence: float = 0.0
        
        # Audio buffer for overlapping windows
        self._audio_buffer: np.ndarray = np.array([], dtype=np.float32)
    
    def _log(self, message: str):
        """Log a message if logger is available."""
        if self.logger:
            try:
                self.logger(message)
            except Exception:
                pass
    
    async def start(self) -> bool:
        """
        Start the CW decoder session.
        
        Returns:
            True if started successfully, False otherwise
        """
        if self._running and self._task and not self._task.done():
            return False
        
        self._running = True
        self._last_error = None
        self._started_at = _utc_now_iso()
        self._stopped_at = None
        self._last_heartbeat_at = self._started_at
        self._task = asyncio.create_task(self._run())
        self._log("cw_decoder_started")
        return True
    
    async def stop(self) -> bool:
        """
        Stop the CW decoder session.
        
        Returns:
            True if stopped successfully, False otherwise
        """
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
        
        self._stopped_at = _utc_now_iso()
        self._log("cw_decoder_stopped")
        return True
    
    async def _run(self):
        """
        Main decode loop.
        
        1. Collect audio window from IQ provider
        2. Decode with CWDecoder
        3. Extract callsigns and emit events
        4. Slide window and repeat
        """
        try:
            while self._running:
                self._last_heartbeat_at = _utc_now_iso()
                
                # Check providers are available
                if not self.iq_provider or not self.sample_rate_provider:
                    await asyncio.sleep(self.poll_interval_s)
                    continue
                
                # Get current sample rate
                source_sample_rate = self.sample_rate_provider()
                if source_sample_rate <= 0:
                    await asyncio.sleep(self.poll_interval_s)
                    continue
                
                # Calculate samples needed for window
                target_samples = int(self.window_seconds * self.target_sample_rate)
                
                # Collect IQ samples in chunks until we have enough for processing
                # (scan_engine returns chunks of ~4096 samples each)
                max_attempts = 100  # Prevent infinite loop
                attempts = 0
                while len(self._audio_buffer) < target_samples and attempts < max_attempts:
                    attempts += 1
                    
                    # Try to get next chunk
                    iq_samples = await asyncio.to_thread(
                        self.iq_provider,
                        4096  # Request chunk size
                    )
                    
                    if iq_samples is None or len(iq_samples) == 0:
                        await asyncio.sleep(0.01)  # Brief wait before retry
                        continue
                    
                    # Convert IQ to audio (magnitude)
                    audio = np.abs(iq_samples).astype(np.float32)
                    
                    # Resample to target rate if needed
                    if source_sample_rate != self.target_sample_rate:
                        from scipy.signal import resample_poly
                        # Calculate rational resampling factors
                        gcd = np.gcd(source_sample_rate, self.target_sample_rate)
                        up = self.target_sample_rate // gcd
                        down = source_sample_rate // gcd
                        audio = resample_poly(audio, up, down).astype(np.float32)
                    
                    # Append to buffer
                    self._audio_buffer = np.concatenate([self._audio_buffer, audio])
                
                # Process if we have enough samples
                if len(self._audio_buffer) >= target_samples:
                    # Take window
                    window = self._audio_buffer[:target_samples]
                    
                    # Decode
                    self._decode_attempts += 1
                    result = await asyncio.to_thread(self.decoder.decode, window)
                    
                    self._last_decode_text = result.text
                    self._last_wpm = result.wpm
                    self._last_confidence = result.confidence
                    
                    # Emit events if callsigns detected and confidence sufficient
                    if result.callsigns and result.confidence >= self.min_confidence:
                        self._callsigns_detected += len(result.callsigns)
                        center_hz = self.frequency_provider() if self.frequency_provider else 0
                        
                        for callsign in result.callsigns:
                            event = {
                                "timestamp": _utc_now_iso(),
                                "mode": "CW",
                                "callsign": callsign,
                                "frequency_hz": center_hz + int(result.dominant_freq_hz),
                                "snr_db": 0.0,  # CW decoder doesn't compute SNR
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
                                    self._log(f"cw_event_callback_failed {exc}")
                    
                    # Slide window (keep overlap)
                    overlap_samples = int(self.overlap_seconds * self.target_sample_rate)
                    if overlap_samples > 0 and len(self._audio_buffer) > target_samples:
                        keep = min(overlap_samples, len(self._audio_buffer) - target_samples)
                        self._audio_buffer = self._audio_buffer[target_samples - keep:]
                    else:
                        self._audio_buffer = np.array([], dtype=np.float32)
                
                await asyncio.sleep(self.poll_interval_s)
                
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._last_error = str(exc)
            self._running = False
            self._log(f"cw_decoder_failed {exc}")
    
    def snapshot(self) -> dict:
        """
        Return current session state for API.
        
        Returns:
            Dict with session statistics and state
        """
        return {
            "enabled": True,
            "running": self._running,
            "target_sample_rate": self.target_sample_rate,
            "window_seconds": self.window_seconds,
            "overlap_seconds": self.overlap_seconds,
            "min_confidence": self.min_confidence,
            "started_at": self._started_at,
            "stopped_at": self._stopped_at,
            "last_heartbeat_at": self._last_heartbeat_at,
            "decode_attempts": self._decode_attempts,
            "events_emitted": self._events_emitted,
            "callsigns_detected": self._callsigns_detected,
            "last_event_at": self._last_event_at,
            "last_decode_text": self._last_decode_text,
            "last_wpm": self._last_wpm,
            "last_confidence": self._last_confidence,
            "last_error": self._last_error,
        }
