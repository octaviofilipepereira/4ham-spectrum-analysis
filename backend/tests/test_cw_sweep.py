# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

"""
Tests for CWSweepDecoder
========================
"""

import asyncio
import types

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_decoder(band_start_hz=14_000_000, band_end_hz=14_070_000,
                  step_hz=6500, dwell_s=0.05, settle_ms=5,
                  on_event=None):
    """Build a CWSweepDecoder with convenient defaults for testing.

    Uses an always-available IQ provider (no queue; returns fresh chunks on
    every call) so that iq_flush() never empties the source and collection
    windows complete immediately.
    """
    from app.decoders.cw_sweep import CWSweepDecoder

    # Return fresh dummy IQ on every call — simulates a live SDR with no gaps.
    _dummy = np.ones(512, dtype=np.complex64)

    def _iq_provider():
        return _dummy.copy()

    parked_at = []
    unparked = []

    def _park(hz):
        parked_at.append(hz)

    def _unpark():
        unparked.append(True)

    decoder = CWSweepDecoder(
        band_start_hz=band_start_hz,
        band_end_hz=band_end_hz,
        step_hz=step_hz,
        dwell_s=dwell_s,
        settle_ms=settle_ms,
        iq_provider=_iq_provider,
        # No-op flush: the provider always returns data, so flushing is
        # irrelevant for unit tests and avoids the "drained queue" trap.
        iq_flush=lambda: None,
        # Same rate as target avoids scipy.signal.resample_poly in tests.
        sample_rate_provider=lambda: 8_000,
        frequency_provider=lambda: 14_035_000,
        scan_park=_park,
        scan_unpark=_unpark,
        on_event=on_event or (lambda e: None),
        target_sample_rate=8_000,
        min_confidence=0.3,
    )

    return decoder, parked_at, unparked


def _stub_result(callsigns=None, confidence=0.90, wpm=12.0, dominant_hz=700.0, text="CQ CT7BFV"):
    """Return a fake CWDecoder result namespace."""
    r = types.SimpleNamespace()
    r.callsigns = callsigns or []
    r.confidence = confidence
    r.wpm = wpm
    r.dominant_freq_hz = dominant_hz
    r.text = text
    return r


# ---------------------------------------------------------------------------
# Unit tests — position generation
# ---------------------------------------------------------------------------

def test_positions_covers_full_band():
    """Positions must start at band_start and the last position == band_end."""
    from app.decoders.cw_sweep import CWSweepDecoder

    # Minimal decoder — no IO needed just to test _build_positions
    d = CWSweepDecoder(
        band_start_hz=14_000_000,
        band_end_hz=14_070_000,
        step_hz=6500,
    )
    positions = d._build_positions()
    assert positions[0] == 14_000_000
    assert positions[-1] == 14_070_000


def test_positions_step_spacing():
    """Consecutive positions must differ by exactly step_hz (except the last)."""
    from app.decoders.cw_sweep import CWSweepDecoder

    d = CWSweepDecoder(
        band_start_hz=14_000_000,
        band_end_hz=14_050_000,
        step_hz=10_000,
    )
    positions = d._build_positions()
    # Interior gaps must equal step_hz
    for a, b in zip(positions, positions[1:-1]):
        assert b - a == 10_000


def test_positions_single_step():
    """When band width equals one step, two positions are returned."""
    from app.decoders.cw_sweep import CWSweepDecoder

    d = CWSweepDecoder(
        band_start_hz=14_000_000,
        band_end_hz=14_006_500,
        step_hz=6500,
    )
    positions = d._build_positions()
    assert len(positions) == 2
    assert positions[0] == 14_000_000
    assert positions[-1] == 14_006_500


def test_positions_partial_band():
    """band_end not divisible by step_hz — last position still == band_end."""
    from app.decoders.cw_sweep import CWSweepDecoder

    d = CWSweepDecoder(
        band_start_hz=14_000_000,
        band_end_hz=14_020_000,
        step_hz=6500,
    )
    positions = d._build_positions()
    assert positions[-1] == 14_020_000


# ---------------------------------------------------------------------------
# Integration tests — lifecycle
# ---------------------------------------------------------------------------

def test_start_stop_lifecycle():
    """start() → snapshot running, stop() → snapshot stopped, unpark called."""
    async def scenario():
        decoder, _, unparked = _make_decoder()

        # Monkey-patch decode to return a no-callsign result immediately
        decoder._decoder.decode = lambda audio: _stub_result()

        started = await decoder.start()
        assert started is True
        assert decoder.snapshot()["running"] is True

        await asyncio.sleep(0.20)  # let at least one position cycle complete

        stopped = await decoder.stop()
        assert stopped is True

        snap = decoder.snapshot()
        assert snap["running"] is False
        assert snap["stopped_at"] is not None
        # unpark must have been called at least once
        assert len(unparked) >= 1

    asyncio.run(scenario())


def test_double_start_returns_false():
    """Calling start() twice returns False on second attempt."""
    async def scenario():
        decoder, _, _ = _make_decoder()
        decoder._decoder.decode = lambda audio: _stub_result()

        await decoder.start()
        result = await decoder.start()
        assert result is False
        await decoder.stop()

    asyncio.run(scenario())


def test_double_stop_returns_false():
    """Calling stop() twice returns False on second attempt."""
    async def scenario():
        decoder, _, _ = _make_decoder()
        decoder._decoder.decode = lambda audio: _stub_result()

        await decoder.start()
        await decoder.stop()
        result = await decoder.stop()
        assert result is False

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Integration tests — event emission
# ---------------------------------------------------------------------------

def test_events_emitted_with_correct_rf_frequency():
    """
    When CWDecoder returns a callsign at dominant_freq_hz=800 and the current
    park position is 14_035_000, the emitted event frequency must be
    14_035_000 + 800 = 14_035_800.
    """
    async def scenario():
        emitted = []

        def _on_event(ev):
            emitted.append(ev)

        band_start = 14_000_000
        band_end = 14_070_000
        step_hz = 6500

        decoder, parked_at, _ = _make_decoder(
            band_start_hz=band_start,
            band_end_hz=band_end,
            step_hz=step_hz,
            dwell_s=0.05,
            settle_ms=5,
            on_event=_on_event,
        )

        dominant_hz = 800.0
        decoder._decoder.decode = lambda audio: _stub_result(
            callsigns=["CT7BFV"],
            confidence=0.95,
            dominant_hz=dominant_hz,
        )

        await decoder.start()
        # Allow enough time for at least two decode attempts
        await asyncio.sleep(0.40)
        await decoder.stop()

        assert len(emitted) >= 1
        first = emitted[0]
        assert first["callsign"] == "CT7BFV"
        assert first["mode"] == "CW"
        # RF frequency = park position + audio-domain tone offset
        # Accept any parked position in the band
        expected_freq = parked_at[0] + int(dominant_hz)
        assert first["frequency_hz"] == expected_freq
        assert first["df_hz"] == int(dominant_hz)

    asyncio.run(scenario())


def test_low_confidence_events_suppressed():
    """Events below min_confidence must NOT be emitted."""
    async def scenario():
        emitted = []

        decoder, _, _ = _make_decoder(
            on_event=lambda e: emitted.append(e),
        )

        # Return confidence well below min_confidence=0.3
        decoder._decoder.decode = lambda audio: _stub_result(
            callsigns=["CT7BFV"],
            confidence=0.05,
        )

        await decoder.start()
        await asyncio.sleep(0.30)
        await decoder.stop()

        assert len(emitted) == 0

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Integration tests — park / flush sequence
# ---------------------------------------------------------------------------

def test_park_called_before_each_position():
    """scan_park must be called once per position in order."""
    async def scenario():
        decoder, parked_at, _ = _make_decoder(
            band_start_hz=14_000_000,
            band_end_hz=14_013_000,  # 3 positions: 14_000_000, 14_006_500, 14_013_000
            step_hz=6500,
            dwell_s=0.03,
            settle_ms=5,
        )

        decoder._decoder.decode = lambda audio: _stub_result()

        positions = decoder._build_positions()
        await decoder.start()
        # Allow enough time for the 3 positions to be visited
        await asyncio.sleep(0.30)
        await decoder.stop()

        # First len(positions) parks must follow band order
        assert len(parked_at) >= len(positions)
        for i, pos in enumerate(positions):
            assert parked_at[i] == pos

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Snapshot shape
# ---------------------------------------------------------------------------

def test_snapshot_contains_sweep_fields():
    """Snapshot must expose sweep-specific fields for the API layer."""
    from app.decoders.cw_sweep import CWSweepDecoder

    d = CWSweepDecoder(
        band_start_hz=14_000_000,
        band_end_hz=14_070_000,
        step_hz=6500,
        dwell_s=5.0,
        settle_ms=100,
        target_sample_rate=8000,
        min_confidence=0.3,
    )
    snap = d.snapshot()

    required_keys = {
        "enabled", "running", "mode", "band_start_hz", "band_end_hz",
        "step_hz", "dwell_s", "settle_ms", "target_sample_rate",
        "min_confidence", "current_position_hz", "position_index",
        "cycle_count", "decode_attempts", "events_emitted",
        "callsigns_detected", "last_decode_text", "last_wpm",
        "last_confidence", "started_at", "stopped_at", "last_error",
    }
    for key in required_keys:
        assert key in snap, f"Missing snapshot key: {key}"

    assert snap["mode"] == "sweep"
    assert snap["band_start_hz"] == 14_000_000
    assert snap["band_end_hz"] == 14_070_000
    assert snap["step_hz"] == 6500
    assert snap["running"] is False
