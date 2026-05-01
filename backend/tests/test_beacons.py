# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
Unit tests for the NCDXF Beacon Analysis backend:

  - catalog.py  : beacon list integrity, schedule formula, slot helpers
  - matched_filter.py : template synthesis, dash detection, ID correlation
  - scheduler.py : SlotDetector integration (synchronous path only)
"""

from __future__ import annotations

import math
import sys
import os
from datetime import datetime, timezone

import numpy as np
import pytest

# Allow running from repo root:  pytest backend/tests/test_beacons.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.beacons.catalog import (
    BANDS,
    BEACONS,
    CYCLE_SECONDS,
    SLOT_SECONDS,
    SLOTS_PER_CYCLE,
    beacon_at,
    current_slot_index,
    next_slot_start,
    seconds_into_slot,
    slot_for,
    all_active_beacons,
    DASH_WINDOWS,
)
from app.beacons.matched_filter import SlotDetector, _build_cw_template


# ─────────────────────────────────────────────────────────────────────────────
# catalog.py
# ─────────────────────────────────────────────────────────────────────────────

class TestCatalogIntegrity:
    def test_exactly_18_beacons(self):
        assert len(BEACONS) == 18

    def test_exactly_5_bands(self):
        assert len(BANDS) == 5

    def test_beacon_indices_contiguous(self):
        assert [b.index for b in BEACONS] == list(range(18))

    def test_band_indices_contiguous(self):
        assert [b.index for b in BANDS] == list(range(5))

    def test_cs3b_is_present(self):
        callsigns = [b.callsign for b in BEACONS]
        assert "CS3B" in callsigns

    def test_band_frequencies(self):
        freqs = [b.freq_hz for b in BANDS]
        assert freqs == [14_100_000, 18_110_000, 21_150_000, 24_930_000, 28_200_000]

    def test_cycle_seconds(self):
        assert CYCLE_SECONDS == 180
        assert SLOT_SECONDS == 10
        assert SLOTS_PER_CYCLE == 18

    def test_status_values_valid(self):
        valid = {"active", "off_air", "intermittent"}
        for b in BEACONS:
            assert b.status in valid, f"{b.callsign} has invalid status '{b.status}'"

    def test_all_active_beacons_subset(self):
        active = all_active_beacons()
        assert all(b.status == "active" for b in active)
        assert len(active) <= 18


class TestScheduleFormula:
    """Verify beacon_at / slot_for are consistent with the NCDXF published table.

    Published spot-checks:
      slot_index=0, band_index=0 → 4U1UN  (beacon 0)
      slot_index=0, band_index=1 → YV5B   (beacon 17, i.e. (0-1) % 18 = 17)
      slot_index=1, band_index=0 → VE8AT  (beacon 1)
      slot_index=14, band_index=0 → CS3B  (beacon 14)
    """

    def test_slot0_band0_is_4U1UN(self):
        assert beacon_at(0, 0).callsign == "4U1UN"

    def test_slot0_band1_is_YV5B(self):
        # (0 - 1) % 18 = 17 → YV5B
        assert beacon_at(0, 1).callsign == "YV5B"

    def test_slot1_band0_is_VE8AT(self):
        assert beacon_at(1, 0).callsign == "VE8AT"

    def test_slot14_band0_is_CS3B(self):
        assert beacon_at(14, 0).callsign == "CS3B"

    def test_all_slots_band0_cover_all_beacons(self):
        """Each beacon appears exactly once per cycle on each band."""
        seen = set()
        for s in range(SLOTS_PER_CYCLE):
            seen.add(beacon_at(s, 0).callsign)
        assert seen == {b.callsign for b in BEACONS}

    def test_slot_for_inverse_of_beacon_at(self):
        """slot_for(i, b) is the inverse of beacon_at(s, b) = BEACONS[i]."""
        for band_idx in range(len(BANDS)):
            for beacon_idx in range(len(BEACONS)):
                s = slot_for(beacon_idx, band_idx)
                assert beacon_at(s, band_idx).index == beacon_idx

    def test_out_of_range_raises(self):
        with pytest.raises(IndexError):
            beacon_at(18, 0)
        with pytest.raises(IndexError):
            beacon_at(0, 5)
        with pytest.raises(IndexError):
            slot_for(18, 0)

    def test_all_bands_cover_all_beacons(self):
        for band_idx in range(len(BANDS)):
            seen = {beacon_at(s, band_idx).callsign for s in range(SLOTS_PER_CYCLE)}
            assert seen == {b.callsign for b in BEACONS}


class TestSlotHelpers:
    def test_current_slot_index_range(self):
        now = datetime.now(timezone.utc)
        idx = current_slot_index(now)
        assert 0 <= idx < SLOTS_PER_CYCLE

    def test_seconds_into_slot_range(self):
        secs = seconds_into_slot()
        assert 0.0 <= secs < SLOT_SECONDS

    def test_next_slot_start_is_future(self):
        now = datetime.now(timezone.utc)
        nxt = next_slot_start(now)
        assert nxt > now

    def test_next_slot_start_aligns_to_10s(self):
        now = datetime.now(timezone.utc)
        nxt = next_slot_start(now)
        assert int(nxt.timestamp()) % SLOT_SECONDS == 0

    def test_slot_index_deterministic(self):
        # A known UTC timestamp: 2026-01-01 00:00:00 UTC → epoch 1735689600
        # epoch % 180 = 1735689600 % 180 = 0  → slot 0
        t = datetime.fromtimestamp(1735689600, tz=timezone.utc)
        assert current_slot_index(t) == 0

    def test_slot_index_at_10s(self):
        t = datetime.fromtimestamp(1735689610, tz=timezone.utc)
        assert current_slot_index(t) == 1

    def test_slot_index_at_170s(self):
        t = datetime.fromtimestamp(1735689770, tz=timezone.utc)  # +170s
        assert current_slot_index(t) == 17

    def test_slot_index_wraps_at_180s(self):
        t = datetime.fromtimestamp(1735689780, tz=timezone.utc)  # +180s → new cycle
        assert current_slot_index(t) == 0


# ─────────────────────────────────────────────────────────────────────────────
# matched_filter.py
# ─────────────────────────────────────────────────────────────────────────────

SR = 8000  # target sample rate for all matched_filter tests


def _make_cw_audio(
    callsign: str,
    sr: int = SR,
    wpm: float = 22.0,
    snr_db: float = 30.0,
    total_s: float = 10.0,
) -> np.ndarray:
    """Synthesise a full 10 s slot with CW ID + 4 dashes at declining power."""
    from app.beacons.matched_filter import _build_cw_template

    total_samples = int(total_s * sr)
    audio = np.zeros(total_samples, dtype=np.float32)

    # CW ID at t=0
    template = _build_cw_template(callsign, sr, wpm)
    id_len = min(len(template), int(1.0 * sr))
    audio[:id_len] += template[:id_len]

    # 4 dashes at the timing windows
    for start_s, end_s, _ in DASH_WINDOWS:
        s0 = int(start_s * sr)
        s1 = min(int(end_s * sr), total_samples)
        audio[s0:s1] += 1.0

    # Add AWGN noise
    signal_rms = float(np.sqrt(np.mean(audio[audio != 0] ** 2))) if np.any(audio != 0) else 1.0
    noise_rms = signal_rms / (10 ** (snr_db / 20.0))
    rng = np.random.default_rng(42)
    audio += rng.normal(0.0, noise_rms, total_samples).astype(np.float32)
    return audio


class TestTemplateSynthesis:
    def test_template_nonempty(self):
        tmpl = _build_cw_template("CS3B", SR)
        assert len(tmpl) > 0

    def test_template_values_binary(self):
        tmpl = _build_cw_template("OH2B", SR)
        assert np.all((tmpl == 0.0) | (tmpl == 1.0))

    def test_template_different_for_different_callsigns(self):
        a = _build_cw_template("CS3B", SR)
        b = _build_cw_template("4U1UN", SR)
        # Different length OR different content
        assert len(a) != len(b) or not np.array_equal(a, b)

    def test_template_scales_with_wpm(self):
        tmpl_20 = _build_cw_template("CS3B", SR, wpm=20.0)
        tmpl_30 = _build_cw_template("CS3B", SR, wpm=30.0)
        # Higher WPM → shorter template
        assert len(tmpl_30) < len(tmpl_20)


class TestSlotDetector:
    _slot_start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def _detector(self, callsign: str = "CS3B") -> SlotDetector:
        return SlotDetector(
            callsign=callsign,
            sample_rate=SR,
            slot_start_utc=self._slot_start,
        )

    def test_detect_returns_expected_keys(self):
        audio = _make_cw_audio("CS3B")
        result = self._detector().detect(audio)
        for key in ("detected", "id_confirmed", "id_confidence",
                    "drift_ms", "dash_levels_detected",
                    "snr_db_100w", "snr_db_10w", "snr_db_1w", "snr_db_100mw"):
            assert key in result, f"Missing key: {key}"

    def test_clean_signal_detected(self):
        audio = _make_cw_audio("CS3B", snr_db=30.0)
        result = self._detector("CS3B").detect(audio)
        assert result["detected"] is True

    def test_clean_signal_4_dashes(self):
        audio = _make_cw_audio("CS3B", snr_db=30.0)
        result = self._detector("CS3B").detect(audio)
        assert result["dash_levels_detected"] == 4

    def test_clean_signal_id_confirmed(self):
        audio = _make_cw_audio("CS3B", snr_db=30.0)
        result = self._detector("CS3B").detect(audio)
        assert result["id_confirmed"] is True

    def test_snr_100w_positive_on_strong_signal(self):
        audio = _make_cw_audio("CS3B", snr_db=30.0)
        result = self._detector("CS3B").detect(audio)
        assert result["snr_db_100w"] is not None
        assert result["snr_db_100w"] > 0.0

    def test_empty_audio_not_detected(self):
        result = self._detector().detect(np.array([], dtype=np.float32))
        assert result["detected"] is False

    def test_pure_noise_low_confidence(self):
        rng = np.random.default_rng(99)
        noise = rng.normal(0.0, 0.01, SR * 10).astype(np.float32)
        result = self._detector("CS3B").detect(noise)
        # Noise should not trigger ID confirm (may detect 0 or 1 dashes by chance)
        assert result["id_confidence"] < 0.5

    def test_wrong_callsign_lower_confidence(self):
        audio = _make_cw_audio("CS3B", snr_db=25.0)
        right = self._detector("CS3B").detect(audio)
        wrong = self._detector("4U1UN").detect(audio)
        assert right["id_confidence"] > wrong["id_confidence"]

    def test_dash_count_monotone_with_snr(self):
        """More dashes detected at high SNR than at very low SNR."""
        high = self._detector("CS3B").detect(_make_cw_audio("CS3B", snr_db=30.0))
        low  = self._detector("CS3B").detect(_make_cw_audio("CS3B", snr_db=3.0))
        assert high["dash_levels_detected"] >= low["dash_levels_detected"]

    def test_drift_ms_none_when_not_confirmed(self):
        rng = np.random.default_rng(7)
        noise = rng.normal(0, 0.001, SR * 10).astype(np.float32)
        result = self._detector("CS3B").detect(noise)
        if not result["id_confirmed"]:
            assert result["drift_ms"] is None

    def test_all_ncdxf_callsigns_template_synthesisable(self):
        """Every callsign in the NCDXF catalog must produce a valid template."""
        for beacon in BEACONS:
            tmpl = _build_cw_template(beacon.callsign, SR)
            assert len(tmpl) > 0, f"Empty template for {beacon.callsign}"
            assert np.any(tmpl > 0), f"All-silence template for {beacon.callsign}"
