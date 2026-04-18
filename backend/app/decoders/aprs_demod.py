# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
#
# APRS FM Demodulator — IQ → Audio → Direwolf pipe
#
# Extracts the 144.800 MHz APRS channel from wideband IQ captured by
# the RTL-SDR scan engine, FM-demodulates, and pipes 16-bit PCM audio
# at 22050 Hz to Direwolf's stdin for AX.25 packet decoding.

import asyncio
import logging
import struct
from typing import Optional

import numpy as np

_log = logging.getLogger(__name__)

# APRS channel frequency (Region 1)
APRS_FREQ_HZ = 144_800_000

# Target audio sample rate for Direwolf
AUDIO_RATE = 22050

# FM deviation for narrow-FM APRS (±5 kHz)
FM_DEVIATION_HZ = 5000

# Channel filter half-bandwidth — keep 12.5 kHz around the carrier
CHANNEL_BW_HZ = 12500


class AprsDemodulator:
    """FM-demodulates APRS from wideband IQ and pipes audio to Direwolf."""

    def __init__(self) -> None:
        self._iq_queue: Optional[asyncio.Queue] = None
        self._task: Optional[asyncio.Task] = None
        self._process: Optional[asyncio.subprocess.Process] = None
        self._dw_log_fp = None
        self._running = False
        # Demod state
        self._prev_sample: complex = 0 + 0j

    async def start(
        self,
        scan_engine,
        direwolf_cmd: list,
        center_hz: int,
        sample_rate: int,
    ) -> bool:
        """Start the IQ→FM→Direwolf pipe.

        Args:
            scan_engine: ScanEngine instance (for register_iq_listener).
            direwolf_cmd: Base Direwolf command list (e.g. ["direwolf", "-t", "0", "-p", "-c", "..."]).
            center_hz: SDR center frequency in Hz.
            sample_rate: SDR sample rate in Hz.
        """
        if self._running:
            return False

        self._running = True
        self._prev_sample = 0 + 0j

        # Compute channel extraction parameters
        offset_hz = APRS_FREQ_HZ - center_hz
        if abs(offset_hz) > sample_rate / 2:
            _log.error(
                "APRS freq %d Hz outside capture bandwidth "
                "(center=%d, sr=%d, offset=%d)",
                APRS_FREQ_HZ, center_hz, sample_rate, offset_hz,
            )
            self._running = False
            return False

        # Decimation factor to bring wideband IQ down to audio rate
        # We first decimate to ~4× audio rate for filtering headroom,
        # then a second stage to the final audio rate.
        intermediate_rate = AUDIO_RATE * 4  # 88200 Hz
        decim1 = max(1, int(sample_rate / intermediate_rate))
        actual_intermediate = sample_rate / decim1
        decim2 = max(1, int(round(actual_intermediate / AUDIO_RATE)))
        actual_audio_rate = actual_intermediate / decim2

        _log.info(
            "APRS demod: center=%d offset=%d sr=%d → decim1=%d (%.0f Hz) "
            "→ decim2=%d (%.0f Hz audio)",
            center_hz, offset_hz, sample_rate,
            decim1, actual_intermediate,
            decim2, actual_audio_rate,
        )

        # Build Direwolf command for stdin pipe mode:
        # direwolf [existing flags] -r 22050 -n 1 -b 16 -
        pipe_cmd = list(direwolf_cmd)
        # Remove any -c config flag pair (we'll re-add it) — keep other flags
        # Actually, keep the command as-is and just append pipe flags
        pipe_cmd.extend(["-r", str(AUDIO_RATE), "-n", "1", "-b", "16", "-"])

        _log.info("APRS demod: starting Direwolf in pipe mode: %s", " ".join(pipe_cmd))

        import os
        env = dict(os.environ)
        env["FOURHAM_MANAGED"] = "1"
        env["FOURHAM_MANAGED_BY"] = "4ham-spectrum-analysis"

        # Log Direwolf stderr for diagnostics
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "logs")
        log_dir = os.path.normpath(log_dir)
        os.makedirs(log_dir, exist_ok=True)
        dw_log_path = os.path.join(log_dir, "direwolf_pipe.log")
        self._dw_log_fp = open(dw_log_path, "w")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *pipe_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=self._dw_log_fp,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
        except Exception as exc:
            _log.error("APRS demod: failed to start Direwolf: %s", exc)
            self._running = False
            return False

        # Register as IQ listener
        self._iq_queue = asyncio.Queue(maxsize=64)
        scan_engine.register_iq_listener(self._iq_queue)

        # Start processing task
        self._task = asyncio.create_task(
            self._demod_loop(
                offset_hz=offset_hz,
                sample_rate=sample_rate,
                decim1=decim1,
                decim2=decim2,
            )
        )

        _log.info("APRS demod: started (PID %d)", self._process.pid)
        return True

    async def stop(self, scan_engine) -> None:
        """Stop the demodulator and kill Direwolf."""
        self._running = False

        if self._iq_queue is not None and scan_engine is not None:
            scan_engine.unregister_iq_listener(self._iq_queue)
        self._iq_queue = None

        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._process is not None:
            try:
                if self._process.stdin:
                    self._process.stdin.close()
            except Exception:
                pass
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=3.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self._process.kill()
                    await asyncio.wait_for(self._process.wait(), timeout=2.0)
                except Exception:
                    pass
            pid = self._process.pid
            self._process = None
            _log.info("APRS demod: Direwolf stopped (PID %s)", pid)

        if self._dw_log_fp is not None:
            try:
                self._dw_log_fp.close()
            except Exception:
                pass
            self._dw_log_fp = None

    @property
    def pid(self) -> Optional[int]:
        return self._process.pid if self._process else None

    @property
    def running(self) -> bool:
        return self._running and self._process is not None

    async def _demod_loop(
        self,
        offset_hz: int,
        sample_rate: int,
        decim1: int,
        decim2: int,
    ) -> None:
        """Consume IQ chunks, FM-demodulate, and pipe audio to Direwolf."""
        # Pre-compute mixer (complex oscillator) parameters
        phase = 0.0
        phase_inc = -2.0 * np.pi * offset_hz / sample_rate  # shift channel to baseband

        while self._running:
            try:
                # Non-blocking get with short sleep to allow cancel
                try:
                    iq_chunk = self._iq_queue.get_nowait()
                except asyncio.QueueEmpty:
                    await asyncio.sleep(0.005)
                    continue

                n = len(iq_chunk)
                if n == 0:
                    continue

                # 1. Frequency-shift: mix the APRS channel down to baseband
                t = np.arange(n)
                mixer = np.exp(1j * (phase + phase_inc * t)).astype(np.complex64)
                phase = (phase + phase_inc * n) % (2.0 * np.pi)
                baseband = iq_chunk * mixer

                # 2. Decimate stage 1 (lowpass via averaging blocks)
                if decim1 > 1:
                    trim = (n // decim1) * decim1
                    baseband = baseband[:trim].reshape(-1, decim1).mean(axis=1)

                # 3. FM demodulate: instantaneous frequency via arg(z[n] * conj(z[n-1]))
                delayed = np.concatenate(([self._prev_sample], baseband[:-1]))
                self._prev_sample = baseband[-1]
                phase_diff = baseband * np.conj(delayed)
                fm_audio = np.angle(phase_diff)

                # Normalize: NBFM deviation maps ±π to ±FM_DEVIATION_HZ
                # Scale to ±1.0 range for 16-bit PCM
                fm_audio = fm_audio / np.pi

                # 4. Decimate stage 2 to final audio rate
                if decim2 > 1:
                    trim2 = (len(fm_audio) // decim2) * decim2
                    fm_audio = fm_audio[:trim2].reshape(-1, decim2).mean(axis=1)

                # 5. Convert to 16-bit PCM and write to Direwolf stdin
                pcm = np.clip(fm_audio * 32000, -32767, 32767).astype(np.int16)
                raw = pcm.tobytes()

                if self._process and self._process.stdin:
                    try:
                        self._process.stdin.write(raw)
                        await self._process.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        _log.warning("APRS demod: Direwolf pipe broken — stopping")
                        self._running = False
                        return

                await asyncio.sleep(0)

            except asyncio.CancelledError:
                return
            except Exception as exc:
                _log.error("APRS demod loop error: %s", exc)
                await asyncio.sleep(0.1)
