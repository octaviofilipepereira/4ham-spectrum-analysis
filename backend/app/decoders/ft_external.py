# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-24 12:00:00 UTC

import asyncio
import gc
import json
import os
import re
import shlex
import subprocess
import tempfile
import wave
from datetime import datetime, timezone

import numpy as np


def _resample_poly_np(x: np.ndarray, up: int, down: int) -> np.ndarray:
    """Polyphase resampler using numpy only — replaces scipy.signal.resample_poly.

    Uses the same Kaiser-windowed FIR design as scipy (half_len=10*max(up,down),
    beta=5.0) and a chunked polyphase filter bank to avoid O(N*up) memory spikes
    on large WSPR windows (>=30 M samples).

    Parameters
    ----------
    x    : 1-D float array (real-valued)
    up   : integer upsample factor
    down : integer downsample factor

    Returns
    -------
    Resampled 1-D float64 array, length ceil(len(x)*up/down).
    """
    from math import gcd as _gcd
    g = _gcd(int(up), int(down))
    up, down = int(up) // g, int(down) // g
    if up == down == 1:
        return x.astype(np.float64, copy=False)

    # ── FIR design (identical to scipy defaults) ──────────────────────────────
    half_len = 10 * max(up, down)
    n_taps = 2 * half_len + 1
    win = np.kaiser(n_taps, 5.0)
    t = np.arange(-half_len, half_len + 1, dtype=np.float64)
    f_c = 1.0 / max(up, down)
    h = f_c * np.sinc(f_c * t) * win
    h *= up / h.sum()                      # unity passband gain after decimation

    # ── Polyphase decomposition ──────────────────────────────────────────────
    # Pad h so its length is divisible by up; h_poly[p, j] = h_pad[p + j*up]
    pad_len = (-n_taps) % up
    h_pad = np.append(h, np.zeros(pad_len))
    n_per_phase = len(h_pad) // up         # taps per polyphase branch
    h_poly = h_pad.reshape(n_per_phase, up).T.copy()  # (up, n_per_phase)
    # Pre-reverse: h_poly_rev[p, j] = h_poly[p, P-1-j] so that
    # dot(seg, h_poly_rev[p]) == dot(seg[::-1], h_poly[p])
    h_poly_rev = h_poly[:, ::-1].copy()    # (up, n_per_phase)

    # ── Input — left-pad with P-1 zeros (filter delay) and right-pad for safety
    x_f = x.astype(np.float64, copy=False)
    n_in = len(x_f)
    # Right-pad: the centre index for the last output sample reaches
    # ((n_out-1)*down + half_len) // up which may exceed n_in by ~half_len//up.
    right_pad = n_per_phase + half_len // up + 1
    x_pad = np.concatenate([
        np.zeros(n_per_phase - 1, dtype=np.float64),
        x_f,
        np.zeros(right_pad, dtype=np.float64),
    ])

    # ── Output allocation ──────────────────────────────────────────────────────
    n_out = int(np.ceil(n_in * up / down))
    out = np.empty(n_out, dtype=np.float64)

    # ── Chunked polyphase filtering ────────────────────────────────────────────
    # For output k: phase = (k*down + half_len) % up
    #               center = (k*down + half_len) // up   (in x-coordinates)
    # out[k] = dot(x_pad[center : center+P], h_poly_rev[phase])
    # Processing CHUNK_OUT samples at a time caps peak memory at
    # ~CHUNK_OUT * n_per_phase * 8 bytes (~14 MB for typical FT8/WSPR ratios).
    _CHUNK_OUT = 4096
    j = np.arange(n_per_phase, dtype=np.int64)  # (P,) — reused each chunk
    for c_start in range(0, n_out, _CHUNK_OUT):
        c_end = min(c_start + _CHUNK_OUT, n_out)
        k = np.arange(c_start, c_end, dtype=np.int64)           # (C,)
        # Polyphase alignment: include filter-delay offset (half_len)
        aligned = k * down + half_len                            # (C,)
        phases = aligned % up                                    # (C,) in [0, up)
        centers = aligned // up                                  # (C,) in x-coords
        # Gather input windows: x_pad[centers[i] + j] for j in 0..P-1
        idx = centers[:, None] + j[None, :]                      # (C, P)
        segs = x_pad[idx]                                        # (C, P)
        h_sel = h_poly_rev[phases]                               # (C, P)
        out[c_start:c_end] = np.einsum('cp,cp->c', segs, h_sel)

    return out


_CALLSIGN_RE = re.compile(r"\b[A-Z]{1,3}\d[A-Z0-9]{0,4}(?:/[A-Z0-9]+)?\b")

# wsprd stdout format (one decode per line):
#   <date> <time>  <snr>  <dt>  <freq_hz>  <drift>  <call>  <grid>  <power_dBm>
# Example:  2502 2220  -22   0.3   7038682   0  CT1FRF IO50  37
_WSPRD_LINE_RE = re.compile(
    r"^\s*\d{4}\s+\d{4}\s+"
    r"([+-]?\d+)\s+"
    r"([+-]?\d+(?:\.\d+)?)\s+"
    r"(\d+(?:\.\d+)?)\s+"
    r"([+-]?\d+)\s+"
    r"(\S+)\s+"
    r"([A-Z]{2}\d{2}[a-z]{0,2})?\s*"
    r"(\d+)?\s*$"
)


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _parse_callsign_from_text(message):
    text = str(message or "").upper()
    if not text:
        return None
    for match in _CALLSIGN_RE.finditer(text):
        candidate = match.group(0)
        if candidate in {"CQ", "QRZ", "DE"}:
            continue
        return candidate
    return None


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def parse_external_decoder_line(line, mode, frequency_hz=None, output_format="jsonl"):
    text = str(line or "").strip()
    if not text:
        return None

    if str(output_format or "jsonl").strip().lower() == "jsonl":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            callsign = payload.get("callsign") or payload.get("call") or _parse_callsign_from_text(payload.get("msg"))
            if not callsign:
                return None
            event_mode = str(payload.get("mode") or mode or "FT8").strip().upper() or "FT8"
            event_frequency = payload.get("frequency_hz")
            if event_frequency is None:
                event_frequency = payload.get("freq_hz")
            if event_frequency is None:
                event_frequency = payload.get("freq")
            if event_frequency is None:
                event_frequency = frequency_hz

            snr_db = payload.get("snr_db")
            if snr_db is None:
                snr_db = payload.get("snr")
            if snr_db is None:
                snr_db = payload.get("db")

            return {
                "timestamp": payload.get("timestamp") or _utc_now_iso(),
                "mode": event_mode,
                "callsign": str(callsign).upper(),
                "frequency_hz": _to_int(event_frequency, default=0),
                "snr_db": _to_float(snr_db, default=0.0),
                "dt_s": _to_float(payload.get("dt_s", payload.get("dt", 0.0)), default=0.0),
                "confidence": _to_float(payload.get("confidence", 0.8), default=0.8),
                "msg": payload.get("msg") or payload.get("raw") or text,
                "raw": "ft_external_decoder",
                "source": "internal_ft_external",
            }

    match = re.match(r"^\s*(\d{4,6}|\*{4})\s+([+-]?\d+)\s+([+-]?\d+(?:\.\d+)?)\s+(\d+)\s+\S\s+(.*)$", text)
    if not match:
        return None

    snr_db = _to_float(match.group(2), default=0.0)
    dt_s = _to_float(match.group(3), default=0.0)
    df_hz = _to_int(match.group(4), default=0)
    message = str(match.group(5) or "").strip()
    callsign = _parse_callsign_from_text(message)
    if not callsign:
        return None

    # The actual RF frequency is dial + audio offset (df_hz).
    # jt9 reports the audio offset in column 4; the dial frequency
    # is passed in as *frequency_hz*.
    dial_hz = _to_int(frequency_hz, default=0)
    rf_frequency_hz = dial_hz + df_hz if dial_hz > 0 else 0

    return {
        "timestamp": _utc_now_iso(),
        "mode": str(mode or "FT8").strip().upper() or "FT8",
        "callsign": callsign,
        "frequency_hz": rf_frequency_hz,
        "snr_db": snr_db,
        "dt_s": dt_s,
        "df_hz": df_hz,
        "confidence": max(0.05, min(0.99, (snr_db + 30.0) / 40.0)),
        "msg": message,
        "raw": "ft_external_decoder",
        "source": "internal_ft_external",
    }


def parse_wsprd_line(line, frequency_hz=None):
    """Parse a single line of wsprd stdout output.

    Format:  <date> <time>  <snr>  <dt>  <freq_hz>  <drift>  <call>  <grid>  <power_dBm>
    Example: 2502 2220  -22   0.3   7038682   0  CT1FRF IO50  37
    """
    text = str(line or "").strip()
    if not text:
        return None
    m = _WSPRD_LINE_RE.match(text)
    if not m:
        return None
    snr_db = _to_float(m.group(1), default=0.0)
    dt_s = _to_float(m.group(2), default=0.0)
    freq_hz = _to_float(m.group(3), default=0.0)
    drift = _to_int(m.group(4), default=0)
    callsign = str(m.group(5) or "").strip().upper()
    grid = str(m.group(6) or "").strip()
    power_dbm = _to_int(m.group(7), default=0)
    if not callsign or callsign in {"CQ", "QRZ", "DE"}:
        return None
    # wsprd reports the exact frequency (dial + audio offset) in Hz.
    event_freq = int(freq_hz) if freq_hz > 100000 else _to_int(frequency_hz, default=0)
    msg_parts = [callsign]
    if grid:
        msg_parts.append(grid)
    if power_dbm:
        msg_parts.append(f"{power_dbm}dBm")
    return {
        "timestamp": _utc_now_iso(),
        "mode": "WSPR",
        "callsign": callsign,
        "frequency_hz": event_freq,
        "snr_db": snr_db,
        "dt_s": dt_s,
        "df_hz": drift,
        "grid": grid,
        "power_dbm": power_dbm,
        "confidence": max(0.05, min(0.99, (snr_db + 30.0) / 40.0)),
        "msg": " ".join(msg_parts),
        "raw": "wsprd_decoder",
        "source": "internal_ft_external",
    }


class ExternalFtDecoder:
    # Standard dial frequencies for FT8 / FT4 / WSPR per band (Hz).
    # Used to compute the IQ frequency shift when the SDR center does
    # not coincide with the target mode's dial frequency.
    DIAL_FREQUENCIES: dict[str, dict[str, int]] = {
        "160m": {"FT8": 1_840_000, "FT4": 1_840_000, "WSPR": 1_836_600},
        "80m":  {"FT8": 3_573_000, "FT4": 3_575_500, "WSPR": 3_568_600},
        "60m":  {"FT8": 5_357_000, "FT4": 5_357_000, "WSPR": 5_287_200},
        "40m":  {"FT8": 7_074_000, "FT4": 7_047_500, "WSPR": 7_038_600},
        "30m":  {"FT8": 10_136_000, "FT4": 10_140_000, "WSPR": 10_138_700},
        "20m":  {"FT8": 14_074_000, "FT4": 14_080_000, "WSPR": 14_095_600},
        "17m":  {"FT8": 18_100_000, "FT4": 18_104_000, "WSPR": 18_104_600},
        "15m":  {"FT8": 21_074_000, "FT4": 21_140_000, "WSPR": 21_094_600},
        "12m":  {"FT8": 24_915_000, "FT4": 24_919_000, "WSPR": 24_924_600},
        "10m":  {"FT8": 28_074_000, "FT4": 28_180_000, "WSPR": 28_124_600},
        "6m":   {"FT8": 50_313_000, "FT4": 50_318_000, "WSPR": 50_293_000},
        "2m":   {"FT8": 144_174_000, "FT4": 144_170_000, "WSPR": 144_489_000},
    }

    def __init__(
        self,
        command_template,
        output_format="jsonl",
        command_templates=None,
        output_formats=None,
        modes=None,
        window_seconds=None,
        poll_s=0.25,
        decode_timeout_s=20.0,
        iq_chunk_size=4096,
        iq_provider=None,
        sample_rate_provider=None,
        frequency_provider=None,
        band_provider=None,
        on_event=None,
        on_window_start=None,
        scan_park=None,
        scan_unpark=None,
        command_runner=None,
        logger=None,
        target_sample_rate=12000,
        wspr_every_n=5,
    ):
        self.command_template = str(command_template or "").strip()
        self.command_templates = dict(command_templates or {})
        self.output_format = str(output_format or "jsonl").strip().lower() or "jsonl"
        self.output_formats = dict(output_formats or {})
        self.modes = [str(mode).strip().upper() for mode in list(modes or ["FT8", "FT4"]) if str(mode).strip()]
        self.window_seconds = dict(window_seconds or {"FT8": 15.0, "FT4": 7.5})
        self.poll_s = max(0.05, float(poll_s))
        self.decode_timeout_s = max(1.0, float(decode_timeout_s))
        self.iq_chunk_size = max(512, int(iq_chunk_size))
        self.iq_provider = iq_provider
        self.sample_rate_provider = sample_rate_provider
        self.frequency_provider = frequency_provider
        self.band_provider = band_provider
        self.on_event = on_event
        self.on_window_start = on_window_start
        self.scan_park = scan_park
        self.scan_unpark = scan_unpark
        self.command_runner = command_runner
        self.logger = logger
        self.target_sample_rate = max(4000, int(target_sample_rate or 12000))
        self.wspr_every_n = max(1, int(wspr_every_n or 5))

        self._task = None
        self._running = False
        self._started_at = None
        self._stopped_at = None
        self._last_heartbeat_at = None
        self._last_window_started_at = None
        self._last_window_completed_at = None
        self._last_event_at = None
        self._events_emitted = 0
        self._windows_processed = 0
        self._decode_invocations = 0
        self._lines_parsed = 0
        self._wspr_skip_counter = 0
        self._last_exit_code = None
        self._last_error = None
        self._last_command = None
        self._last_output_preview = []
        # Set to True by set_modes() when the mode changes mid-scan, so that
        # the current window (which may be a long WSPR 120 s capture) aborts
        # immediately and the new mode starts on the next loop iteration.
        self._abort_window = False

    def _log(self, message):
        if not self.logger:
            return
        try:
            self.logger(message)
        except Exception:
            return

    async def start(self):
        if self._running and self._task and not self._task.done():
            return False
        if not self.command_template:
            self._last_error = "ft_external_missing_command"
            return False

        self._running = True
        self._last_error = None
        self._started_at = _utc_now_iso()
        self._stopped_at = None
        self._last_heartbeat_at = self._started_at
        self._task = asyncio.create_task(self._run())
        self._log("ft_external_started")
        return True

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._stopped_at = _utc_now_iso()
        self._log("ft_external_stopped")
        return True

    def set_modes(self, modes):
        """Update the active decode modes at runtime.

        The running _run() loop picks up the new list on the next
        iteration.  If the current window is a long WSPR capture and the new
        mode list no longer includes WSPR, the window abort flag is set so
        _wait_for_slot_boundary() and _collect_audio_window() return early,
        letting the loop restart with the new mode immediately.
        """
        new_modes = [
            str(m).strip().upper()
            for m in list(modes or [])
            if str(m).strip()
        ]
        if not new_modes:
            new_modes = ["FT8", "FT4"]
        old_modes = list(self.modes)
        self.modes = new_modes
        # If we are switching away from a mode (e.g. WSPR → FT8), signal the
        # current window to abort so the new mode is picked up quickly.
        if set(old_modes) != set(new_modes):
            self._abort_window = True
        self._log(f"ft_external_modes_updated modes={self.modes}")
        return list(self.modes)

    async def _run(self):
        mode_index = 0
        try:
            while self._running:
                self._last_heartbeat_at = _utc_now_iso()
                if not self.iq_provider or not self.sample_rate_provider:
                    await asyncio.sleep(self.poll_s)
                    continue

                if not self.modes:
                    await asyncio.sleep(self.poll_s)
                    continue

                mode = self.modes[mode_index % len(self.modes)]
                mode_index += 1
                # Clear any leftover abort flag from the previous iteration
                # so a fresh window can run.
                self._abort_window = False

                window_s = float(self.window_seconds.get(mode, 15.0) or 15.0)
                source_sample_rate = _to_int(self.sample_rate_provider(), default=0)
                if source_sample_rate <= 0:
                    await asyncio.sleep(self.poll_s)
                    continue

                # Pre-check: verify frequency is known before waiting for slot.
                # Re-evaluated after the wait to pick up any band/mode change.
                center_hz = _to_int(
                    self.frequency_provider() if self.frequency_provider else 0,
                    default=0,
                )
                band = str(
                    self.band_provider() if self.band_provider else ""
                ).strip().lower()
                dial_hz = int(
                    self.DIAL_FREQUENCIES.get(band, {}).get(mode, center_hz)
                    or center_hz
                )

                # Guard: skip window if SDR centre not yet known
                # (scan hasn't started or provider returned 0).
                if dial_hz <= 0:
                    self._log(
                        f"ft_external_skip_no_freq mode={mode} band={band} "
                        f"center_hz={center_hz} dial_hz={dial_hz}"
                    )
                    await asyncio.sleep(self.poll_s)
                    continue

                # Skip WSPR unless it's the Nth opportunity.
                # This keeps FT8/FT4 cycling fast and only runs
                # the expensive 120 s WSPR window periodically.
                # Placed AFTER the frequency guard so the counter
                # only increments when a real window could run.
                # Skip logic is bypassed when WSPR is the only active mode
                # (user explicitly selected WSPR — run every 2-minute slot).
                if mode == "WSPR" and self.wspr_every_n > 1 and len(self.modes) > 1:
                    self._wspr_skip_counter += 1
                    if self._wspr_skip_counter % self.wspr_every_n != 0:
                        continue

                # Remember the band BEFORE waiting so we can detect a
                # band change that happened during the slot wait.
                band_before_wait = band

                # ── Wait for the next FT8/FT4 slot boundary ──
                slot_ok = await self._wait_for_slot_boundary(window_s)
                if not slot_ok:
                    # Mode changed while waiting — skip this window entirely
                    # and pick up the new mode on the next iteration.
                    self._log(f"ft_external_slot_aborted mode={mode}")
                    continue

                # Re-evaluate band and dial frequency after the slot wait.
                # If the user changed band or the scan restarted during the
                # wait (which can be up to 120 s for WSPR), the park target
                # and wsprd frequency argument must reflect the current band.
                center_hz = _to_int(
                    self.frequency_provider() if self.frequency_provider else 0,
                    default=0,
                )
                band = str(
                    self.band_provider() if self.band_provider else ""
                ).strip().lower()
                dial_hz = int(
                    self.DIAL_FREQUENCIES.get(band, {}).get(mode, center_hz)
                    or center_hz
                )
                if dial_hz <= 0:
                    self._log(
                        f"ft_external_skip_no_freq_post_wait mode={mode} band={band}"
                    )
                    continue

                # If the band changed while we were waiting for the slot
                # boundary, the IQ data at the start of this window came
                # from the OLD scan (wrong frequency).  Skip this window and
                # let the next iteration start a fresh capture on the new band.
                if band != band_before_wait and band_before_wait:
                    self._log(
                        f"ft_external_band_changed_abort"
                        f" old={band_before_wait} new={band} mode={mode}"
                    )
                    continue
                # In auto-scan mode the SDR hops across the band.
                # Parking holds it on the dial frequency so every
                # IQ sample in the window comes from ONE frequency.
                if self.scan_park:
                    try:
                        self.scan_park(dial_hz)
                    except Exception:
                        pass
                    await asyncio.sleep(0.05)  # 50 ms SDR settle

                try:
                    # Reset the IQ provider so we only get fresh samples
                    if self.on_window_start:
                        try:
                            self.on_window_start()
                        except Exception:
                            pass

                    self._last_window_started_at = _utc_now_iso()

                    # After parking, the SDR center IS the dial frequency
                    # so freq_shift_hz should be 0 (or nearly so).  For
                    # non-parked (fixed) scans we still compute the shift
                    # from the actual center.
                    parked_center = _to_int(
                        self.frequency_provider() if self.frequency_provider else 0,
                        default=0,
                    )
                    freq_shift_hz = float(dial_hz - parked_center) if parked_center else 0.0

                    # For WSPR, decimate at collection time to avoid OOM.
                    # At 2048 kHz, 120 s = ~1.97 GB complex64.
                    # Striding to ~48 kHz keeps the buffer under 60 MB;
                    # wsprd only needs audio up to ~3 kHz so 48 kHz is fine.
                    _WSPR_MAX_COLLECT_RATE_HZ = 48_000
                    if mode == "WSPR" and source_sample_rate > _WSPR_MAX_COLLECT_RATE_HZ:
                        collection_stride = max(1, source_sample_rate // _WSPR_MAX_COLLECT_RATE_HZ)
                    else:
                        collection_stride = 1

                    audio, decode_sample_rate = await self._collect_audio_window(
                        window_s=window_s,
                        source_sample_rate=source_sample_rate,
                        freq_shift_hz=freq_shift_hz,
                        collection_stride=collection_stride,
                    )
                    if self._abort_window:
                        # Mode changed during audio collection — discard
                        # the partial buffer and start fresh.
                        self._log(f"ft_external_window_aborted mode={mode}")
                        continue
                    if audio is None or audio.size == 0:
                        self._log(f"ft_external_empty_audio mode={mode}")
                        await asyncio.sleep(self.poll_s)
                        continue

                    frequency_hz = dial_hz or center_hz
                    self._decode_invocations += 1
                    result = await asyncio.to_thread(
                        self._decode_audio_window,
                        audio,
                        decode_sample_rate,
                        mode,
                        frequency_hz,
                    )
                    self._last_exit_code = _to_int(result.get("returncode"), default=0)
                    self._lines_parsed += int(result.get("lines_parsed") or 0)
                    self._windows_processed += 1
                    self._last_window_completed_at = _utc_now_iso()
                finally:
                    # ── Always unpark so the scan sweep resumes ──
                    if self.scan_unpark:
                        try:
                            self.scan_unpark()
                        except Exception:
                            pass

                await asyncio.sleep(self.poll_s)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._last_error = str(exc)
            self._running = False
            self._log(f"ft_external_failed {exc}")

    async def _wait_for_slot_boundary(self, period_s):
        """Sleep until the next FT8/FT4 slot boundary.

        FT8 slots start at UTC seconds divisible by *period_s*
        (15.0 for FT8, 7.5 for FT4).  Starting the IQ capture at the
        boundary ensures jt9 receives a complete, time-aligned window.

        Returns True if the wait completed normally, False if aborted early
        due to a mode change (self._abort_window was set).
        """
        import time as _time
        now = _time.time()
        period = float(period_s)
        if period <= 0:
            return True
        # Next boundary: ceil(now / period) * period
        next_boundary = (int(now / period) + 1) * period
        wait = next_boundary - now
        if wait > 0 and wait <= period:
            # Flush stale IQ from the broadcast buffer while we wait,
            # so _collect_audio_window starts with fresh samples.
            deadline = _time.time() + wait - 0.05
            while _time.time() < deadline and self._running and not self._abort_window:
                step = min(0.25, deadline - _time.time())
                if step > 0:
                    await asyncio.sleep(step)
            if self._abort_window:
                return False
            # Final tiny wait to hit the boundary precisely
            remaining = next_boundary - _time.time()
            if remaining > 0:
                await asyncio.sleep(remaining)
        return True

    # Maximum number of samples to process in one frequency-shift
    # chunk.  Keeps peak memory under ~16 MB per chunk instead of
    # allocating a monolithic array for the full window (which was
    # 2-4 GB for WSPR at 2 MHz and caused OOM kills).
    _FREQ_SHIFT_CHUNK = 1_048_576  # ~1 M samples → ~8 MB complex64

    async def _collect_audio_window(self, window_s, source_sample_rate, freq_shift_hz=0.0,
                                     collection_stride=1):
        stride = max(1, int(collection_stride))
        # When stride > 1 we decimate the IQ stream at collection time,
        # reducing the effective sample rate before the buffer is allocated.
        # This prevents OOM for WSPR (120 s × 2048 kHz ≈ 2 GB → 46 MB at 48 kHz).
        effective_source_rate = source_sample_rate // stride if stride > 1 else source_sample_rate
        source_target_samples = max(1, int(float(window_s) * int(effective_source_rate)))
        # Pre-allocate a single buffer to avoid the double-memory peak
        # of keeping a chunks list AND the concatenated array.
        buffer = np.empty(source_target_samples, dtype=np.complex64)
        total = 0
        reads_since_yield = 0
        while self._running and not self._abort_window and total < source_target_samples:
            iq = self.iq_provider(self.iq_chunk_size)
            if iq is None:
                await asyncio.sleep(0.01)
                reads_since_yield = 0
                continue
            array = np.asarray(iq)
            if array.size == 0:
                await asyncio.sleep(0.005)
                reads_since_yield = 0
                continue
            # Decimate the IQ chunk to reduce memory pressure.
            # Keep complex IQ — do NOT take real part here; USB
            # demodulation requires decimation first to avoid aliasing
            # wideband noise into the audio passband.
            if stride > 1:
                array = array[::stride]
            remaining = source_target_samples - total
            chunk_size = min(array.size, remaining)
            buffer[total:total + chunk_size] = array[:chunk_size].astype(np.complex64, copy=False)
            total += chunk_size
            del array, iq
            reads_since_yield += 1
            # Yield periodically so other async tasks (IQ pump, WS) can run
            if reads_since_yield >= 4:
                await asyncio.sleep(0)
                reads_since_yield = 0

        if total == 0 or self._abort_window:
            del buffer
            return None, int(effective_source_rate)

        # Trim buffer to actual size collected
        signal = buffer[:total]
        del buffer

        # ── Offload heavy DSP to a worker thread ──────────────
        # Frequency shift, resample_poly and gc.collect are pure CPU
        # that block the event loop for ~2 s (FT8) to ~10 s (WSPR).
        # Running them in to_thread keeps WebSocket / IQ pump alive.
        audio, target_rate = await asyncio.to_thread(
            self._process_iq_to_audio_from_signal,
            signal,
            effective_source_rate,   # use the decimated rate, not the SDR rate
            freq_shift_hz,
            window_s,
        )
        return audio, target_rate

    def _process_iq_to_audio_from_signal(self, signal, source_sample_rate,
                                         freq_shift_hz, window_s):
        """Synchronous DSP: freq shift → resample → pad.

        Called via asyncio.to_thread so it does NOT block the event loop.
        Takes a pre-allocated signal array (no chunks concatenation needed).
        """
        # ── Frequency shift (chunked to cap peak memory) ──
        if abs(freq_shift_hz) > 0.5 and np.iscomplexobj(signal) and signal.size > 0:
            source_rate_f = float(source_sample_rate)
            phase_inc = -2.0 * np.pi * freq_shift_hz / source_rate_f
            chunk_size = self._FREQ_SHIFT_CHUNK
            offset = 0
            while offset < signal.size:
                end = min(offset + chunk_size, signal.size)
                n = np.arange(offset, end, dtype=np.float64)
                shift = np.exp(1j * phase_inc * n).astype(np.complex64)
                signal[offset:end] *= shift
                del n, shift
                offset = end
            self._log(f"ft_external_freq_shift {freq_shift_hz:+.0f} Hz ({signal.size} samples)")

        source_rate = max(1, int(source_sample_rate))
        target_rate = max(1, int(self.target_sample_rate))

        if source_rate != target_rate and signal.size > 8:
            gcd = int(np.gcd(source_rate, target_rate))
            up = max(1, target_rate // gcd)
            down = max(1, source_rate // gcd)
            if np.iscomplexobj(signal):
                real_part = signal.real.copy()
                del signal
                gc.collect()
                i_dec = _resample_poly_np(real_part, up=up, down=down)
                del real_part
                audio = i_dec.astype(np.float32, copy=False)
                del i_dec
            else:
                audio = _resample_poly_np(signal, up=up, down=down).astype(
                    np.float32, copy=False
                )
                del signal
            gc.collect()
        else:
            if np.iscomplexobj(signal):
                audio = signal.real.astype(np.float32)
            else:
                audio = signal.astype(np.float32)
            del signal

        target_samples = max(1, int(float(window_s) * int(target_rate)))
        if audio.size > target_samples:
            audio = audio[:target_samples]
        elif audio.size < target_samples:
            pad = np.zeros(target_samples - audio.size, dtype=np.float32)
            audio = np.concatenate([audio, pad], axis=0)
        return audio, target_rate

    def _process_iq_to_audio(self, chunks, source_target_samples,
                             source_sample_rate, freq_shift_hz, window_s):
        """Synchronous DSP: concat → freq shift → resample → pad.

        Called via asyncio.to_thread so it does NOT block the event loop.
        """
        signal = np.concatenate(chunks, axis=0)
        del chunks  # free list of references early
        if signal.size > source_target_samples:
            signal = signal[:source_target_samples]

        # ── Frequency shift (chunked to cap peak memory) ──
        # When the target dial frequency differs from the SDR center
        # (e.g. FT4 at 7.047.5 MHz while SDR is centered on 7.074 MHz),
        # we multiply the IQ by exp(-j·2π·Δf·n/fs) to move the target
        # signal to baseband before the anti-alias decimation filter
        # removes it.
        #
        # The shift is applied in chunks of _FREQ_SHIFT_CHUNK samples
        # so that the temporary n / shift arrays stay small (~16 MB)
        # instead of allocating gigabytes for long WSPR windows.
        if abs(freq_shift_hz) > 0.5 and np.iscomplexobj(signal) and signal.size > 0:
            source_rate_f = float(source_sample_rate)
            # phase_inc kept in float64 for precision — large sample indices
            # (>16 M for WSPR) would lose accuracy in float32.
            phase_inc = -2.0 * np.pi * freq_shift_hz / source_rate_f
            chunk_size = self._FREQ_SHIFT_CHUNK
            offset = 0
            while offset < signal.size:
                end = min(offset + chunk_size, signal.size)
                # float64 index → accurate phase even at offset >200 M
                n = np.arange(offset, end, dtype=np.float64)
                shift = np.exp(1j * phase_inc * n).astype(np.complex64)
                signal[offset:end] *= shift
                del n, shift
                offset = end
            self._log(f"ft_external_freq_shift {freq_shift_hz:+.0f} Hz ({signal.size} samples)")

        source_rate = max(1, int(source_sample_rate))
        target_rate = max(1, int(self.target_sample_rate))

        if source_rate != target_rate and signal.size > 8:
            gcd = int(np.gcd(source_rate, target_rate))
            up = max(1, target_rate // gcd)
            down = max(1, source_rate // gcd)
            if np.iscomplexobj(signal):
                # Decimate I and Q channels SEPARATELY so the anti-alias
                # filter removes everything outside ±target_rate/2 BEFORE
                # we discard the imaginary part (USB demodulation).
                real_part = signal.real.copy()
                del signal  # free ~N×8 bytes before resampling
                gc.collect()
                i_dec = _resample_poly_np(real_part, up=up, down=down)
                del real_part
                # USB = Re(analytic signal)  — the positive-frequency
                # content (FT8 tones at +200…+3000 Hz) is preserved in I.
                audio = i_dec.astype(np.float32, copy=False)
                del i_dec
            else:
                audio = _resample_poly_np(signal, up=up, down=down).astype(
                    np.float32, copy=False
                )
                del signal
            gc.collect()
        else:
            if np.iscomplexobj(signal):
                audio = signal.real.astype(np.float32)
            else:
                audio = signal.astype(np.float32)
            del signal

        target_samples = max(1, int(float(window_s) * int(target_rate)))
        if audio.size > target_samples:
            audio = audio[:target_samples]
        elif audio.size < target_samples:
            pad = np.zeros(target_samples - audio.size, dtype=np.float32)
            audio = np.concatenate([audio, pad], axis=0)
        return audio, target_rate

    def _decode_audio_window(self, audio, sample_rate, mode, frequency_hz):
        with tempfile.NamedTemporaryFile(prefix="ft_external_", suffix=".wav", delete=False) as temp_file:
            wav_path = temp_file.name
        try:
            self._write_wav(audio, sample_rate, wav_path)
            mode_upper = str(mode or "FT8").strip().upper() or "FT8"
            mode_lower = mode_upper.lower()
            mode_flag = f"--{mode_lower}"
            if mode_upper == "FT8":
                mode_flag = "--ft8"
            elif mode_upper == "FT4":
                mode_flag = "--ft4"
            period_s = float(self.window_seconds.get(mode_upper, 15.0) or 15.0)
            freq_mhz = float(frequency_hz or 0) / 1_000_000.0

            # Pick the command template for this mode (per-mode override
            # or the global fallback).
            cmd_template = self.command_templates.get(mode_upper) or self.command_template

            command = cmd_template.format(
                wav_path=wav_path,
                mode=mode_upper,
                mode_lower=mode_lower,
                mode_flag=mode_flag,
                period_s=period_s,
                period_int=int(period_s),
                sample_rate=int(sample_rate),
                frequency_hz=int(frequency_hz or 0),
                frequency_mhz=f"{freq_mhz:.6f}",
            )
            self._last_command = command
            runner = self.command_runner or self._run_command
            # wsprd needs more time than jt9 — allow up to 90 s for deep decode
            effective_timeout_s = 90.0 if mode_upper == "WSPR" else self.decode_timeout_s
            run_result = runner(command, timeout_s=effective_timeout_s)
            stdout = str(run_result.get("stdout") or "")
            stderr = str(run_result.get("stderr") or "")
            merged_lines = [line for line in (stdout + "\n" + stderr).splitlines() if str(line).strip()]
            self._last_output_preview = merged_lines[:10]

            # Pick the output format for this mode (per-mode override or global).
            effective_format = (
                self.output_formats.get(mode_upper)
                or self.output_format
            )

            lines_parsed = 0
            for line in merged_lines:
                if effective_format == "wsprd":
                    parsed = parse_wsprd_line(line, frequency_hz=frequency_hz)
                else:
                    parsed = parse_external_decoder_line(
                        line=line,
                        mode=mode,
                        frequency_hz=frequency_hz,
                        output_format=effective_format,
                    )
                if not parsed:
                    continue
                lines_parsed += 1
                if self.on_event:
                    event_result = self.on_event(parsed)
                    if asyncio.iscoroutine(event_result):
                        try:
                            asyncio.run(event_result)
                        except RuntimeError:
                            pass
                self._events_emitted += 1
                self._last_event_at = _utc_now_iso()
            return {
                "returncode": _to_int(run_result.get("returncode"), default=0),
                "lines_parsed": lines_parsed,
            }
        except Exception as exc:
            self._last_error = str(exc)
            self._log(f"ft_external_decode_failed {exc}")
            return {"returncode": -1, "lines_parsed": 0}
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass

    def _write_wav(self, audio, sample_rate, wav_path):
        max_abs = float(np.max(np.abs(audio))) if audio.size else 0.0
        if max_abs > 0:
            normalized = audio / max_abs
        else:
            normalized = audio
        pcm16 = np.clip(normalized * 32767.0, -32768.0, 32767.0).astype(np.int16)
        with wave.open(wav_path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(int(sample_rate))
            wav.writeframes(pcm16.tobytes())

    def _run_command(self, command, timeout_s=20.0):
        args = shlex.split(command)
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout_s)),
            check=False,
        )
        return {
            "returncode": int(proc.returncode),
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
        }

    def snapshot(self):
        running = bool(self._running and self._task and not self._task.done())
        return {
            "enabled": running,
            "running": running,
            "command_template": self.command_template,
            "command_templates": dict(self.command_templates),
            "output_format": self.output_format,
            "output_formats": dict(self.output_formats),
            "modes": list(self.modes),
            "window_seconds": dict(self.window_seconds),
            "poll_s": self.poll_s,
            "decode_timeout_s": self.decode_timeout_s,
            "iq_chunk_size": self.iq_chunk_size,
            "started_at": self._started_at,
            "stopped_at": self._stopped_at,
            "last_heartbeat_at": self._last_heartbeat_at,
            "last_window_started_at": self._last_window_started_at,
            "last_window_completed_at": self._last_window_completed_at,
            "decode_invocations": int(self._decode_invocations),
            "windows_processed": int(self._windows_processed),
            "lines_parsed": int(self._lines_parsed),
            "events_emitted": int(self._events_emitted),
            "last_event_at": self._last_event_at,
            "last_exit_code": self._last_exit_code,
            "last_error": self._last_error,
            "last_command": self._last_command,
            "last_output_preview": list(self._last_output_preview),
            "wspr_every_n": self.wspr_every_n,
            "wspr_skip_counter": int(self._wspr_skip_counter),
        }
