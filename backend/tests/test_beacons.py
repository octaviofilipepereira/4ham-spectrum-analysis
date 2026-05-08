# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
Unit tests for the NCDXF Beacon Analysis backend:

  - catalog.py  : beacon list integrity, schedule formula, slot helpers
  - matched_filter.py : template synthesis, dash detection, ID correlation
  - scheduler.py : SlotDetector integration (synchronous path only)
"""

from __future__ import annotations

import asyncio
import math
import sys
import os
from datetime import datetime, timezone
from statistics import median

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
from app.beacons.scheduler import apply_catalog_status_rules, _downsample_envelope
from app.beacons.matched_filter import (
    DETECT_SCORE_THRESHOLD,
    SlotDetector,
    _build_cw_template,
    _combined_detect_score,
)
from app.api import beacons as beacon_api
from app.beacons.propagation import build_beacon_map_contacts, build_beacon_propagation_summary
from app.beacons.public_payloads import public_beacon_heatmap_cell, public_beacon_observation


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


def test_public_beacon_payload_helpers_strip_internal_diagnostics():
    observation = public_beacon_observation({
        "slot_start_utc": "2026-05-03T12:00:00+00:00",
        "detected": True,
        "id_confirmed": True,
        "id_confidence": 0.33,
        "drift_ms": 128.0,
        "dash_levels_detected": 3,
    })
    heatmap = public_beacon_heatmap_cell({
        "beacon_index": 14,
        "band_name": "20m",
        "detections": 3,
        "id_confirmed": 1,
        "best_id_confirmed": 1,
        "best_dashes": 3,
    })

    assert observation is not None
    assert "id_confirmed" not in observation
    assert "id_confidence" not in observation
    assert "drift_ms" not in observation
    assert observation["dash_levels_detected"] == 3

    assert heatmap is not None
    assert "id_confirmed" not in heatmap
    assert "best_id_confirmed" not in heatmap
    assert heatmap["best_dashes"] == 3


def test_beacon_public_api_routes_strip_internal_diagnostics(monkeypatch):
    slot_start = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    class DummyDb:
        def get_beacon_observations(self, **kwargs):
            return [{
                "id": 42,
                "slot_start_utc": slot_start,
                "slot_index": 14,
                "beacon_callsign": "CS3B",
                "beacon_index": 14,
                "beacon_location": "Madeira, Portugal",
                "beacon_status": "active",
                "band_name": "20m",
                "freq_hz": 14100000,
                "detected": True,
                "id_confirmed": True,
                "id_confidence": 0.21,
                "drift_ms": 115.0,
                "dash_levels_detected": 4,
                "snr_db_100w": 2.7,
                "snr_db_10w": 1.4,
                "snr_db_1w": 0.6,
                "snr_db_100mw": -0.2,
                "recorded_at": slot_start,
            }]

        def get_beacon_heatmap(self, **kwargs):
            return [{
                "beacon_index": 14,
                "band_name": "20m",
                "total_slots": 4,
                "detections": 3,
                "id_confirmed": 1,
                "best_snr_db": 2.7,
                "best_dashes": 4,
                "best_id_confirmed": 1,
                "best_detected_utc": slot_start,
                "latest_detected_utc": slot_start,
            }]

    monkeypatch.setattr(beacon_api.state, "db", DummyDb())

    matrix_payload = asyncio.run(beacon_api.beacon_matrix())
    matrix_cell = matrix_payload["matrix"][14][0]
    assert matrix_cell is not None
    assert "id_confirmed" not in matrix_cell
    assert "id_confidence" not in matrix_cell
    assert "drift_ms" not in matrix_cell

    heatmap_payload = asyncio.run(beacon_api.beacon_heatmap(hours=12.0))
    heatmap_cell = heatmap_payload["matrix"][14][0]
    assert heatmap_cell is not None
    assert "id_confirmed" not in heatmap_cell
    assert "best_id_confirmed" not in heatmap_cell

    observations_payload = asyncio.run(
        beacon_api.beacon_observations(
            limit=10,
            offset=0,
            band=None,
            callsign=None,
            detected_only=False,
            hours=None,
        )
    )
    observation = observations_payload["observations"][0]
    assert observations_payload["count"] == 1
    assert "id_confirmed" not in observation
    assert "id_confidence" not in observation
    assert "drift_ms" not in observation


def test_beacon_analytics_overview_aggregates_existing_surfaces(monkeypatch):
    slot_start = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    class DummyDb:
        def get_settings(self):
            return {"station": {"locator": "IM58sm", "callsign": "CT7BFV"}}

        def get_beacon_heatmap(self, **kwargs):
            assert kwargs["hours"] == 12.0
            return [{
                "beacon_index": 14,
                "band_name": "20m",
                "total_slots": 6,
                "detections": 4,
                "id_confirmed": 2,
                "best_snr_db": 8.5,
                "best_dashes": 4,
                "best_id_confirmed": 1,
                "best_detected_utc": slot_start,
                "latest_detected_utc": slot_start,
            }]

        def get_beacon_observations(self, **kwargs):
            assert kwargs["detected_only"] is False
            assert kwargs["hours"] == pytest.approx(3.0)
            return [{
                "id": 42,
                "slot_start_utc": slot_start,
                "slot_index": 14,
                "beacon_callsign": "CS3B",
                "beacon_index": 14,
                "beacon_location": "Madeira, Portugal",
                "beacon_status": "active",
                "band_name": "20m",
                "freq_hz": 14100000,
                "detected": True,
                "id_confirmed": True,
                "id_confidence": 0.98,
                "drift_ms": 21.4,
                "dash_levels_detected": 4,
                "snr_db_100w": 17.2,
                "snr_db_10w": 10.4,
                "snr_db_1w": 6.3,
                "snr_db_100mw": 2.1,
                "recorded_at": slot_start,
            }]

    monkeypatch.setattr(beacon_api.state, "db", DummyDb())

    class DummyIonosphericCache:
        def get_summary(self, latitude, longitude):
            assert latitude == pytest.approx(38.0, abs=1.0)
            assert longitude == pytest.approx(-9.0, abs=2.0)
            return {
                "kp": 2.3,
                "kp_condition": "Unsettled",
                "sfi": 158.0,
                "fof2_estimated_mhz": 9.6,
                "qth": {"lat": latitude, "lon": longitude},
                "bands": {
                    "20m": {"status": "Open", "open": True, "skip_km": 800, "muf_at_3000km": 22.0},
                    "17m": {"status": "Marginal", "open": True, "skip_km": 1200, "muf_at_3000km": 18.0},
                    "15m": {"status": "Closed", "open": False, "skip_km": 0, "muf_at_3000km": 12.0},
                    "12m": {"status": "Closed", "open": False, "skip_km": 0, "muf_at_3000km": 12.0},
                    "10m": {"status": "Closed", "open": False, "skip_km": 0, "muf_at_3000km": 12.0},
                },
                "last_update": slot_start,
                "source": "NOAA SWPC",
            }

    monkeypatch.setattr(beacon_api, "ionospheric_cache", DummyIonosphericCache())

    payload = asyncio.run(
        beacon_api.beacon_analytics_overview(
            heatmap_hours=12.0,
            propagation_window_minutes=180,
            forecast_window_minutes=180,
            limit=10000,
        )
    )

    assert payload["status"] == "ok"
    assert payload["kind"] == "beacon_analytics"
    assert payload["source_kind"] == "live"
    assert payload["kpis"]["monitored_slots"] == 6
    assert payload["kpis"]["detected_slots"] == 4
    assert payload["kpis"]["detected_beacons"] == 1
    assert payload["kpis"]["best_band"]["band"] == "20m"
    assert payload["recent_activity"]["bands"] == ["20m", "17m", "15m", "12m", "10m"]
    assert payload["recent_activity"]["beacons"][14] == "CS3B"
    assert payload["recent_activity"]["matrix"][14][0]["detections"] == 4
    assert payload["propagation"]["overall"]["state"] == "Excellent"
    assert payload["reading"]["state"] == "aligned"
    assert payload["reading"]["bands"][0]["expected_state"] == "Open"
    assert payload["forecast"]["kind"] == "nowcast"
    assert payload["forecast"]["valid_for_minutes"] == 180


def test_build_beacon_map_contacts_keeps_latest_detection_per_callsign():
    settings = {"station": {"callsign": "CT7BFV", "locator": "IM58sm"}}
    rows = [
        {
            "slot_start_utc": "2026-05-03T10:00:00+00:00",
            "beacon_callsign": "YV5B",
            "beacon_index": 17,
            "band_name": "20m",
            "detected": True,
            "dash_levels_detected": 1,
            "snr_db_100w": 4.2,
        },
        {
            "slot_start_utc": "2026-05-03T10:15:00+00:00",
            "beacon_callsign": "YV5B",
            "beacon_index": 17,
            "band_name": "17m",
            "detected": True,
            "dash_levels_detected": 2,
            "snr_db_100w": 6.1,
        },
    ]

    payload = build_beacon_map_contacts(rows, settings, window_minutes=60)

    assert payload["kind"] == "beacon"
    assert payload["contact_count"] == 1
    assert payload["contacts"][0]["callsign"] == "YV5B"
    assert payload["contacts"][0]["band"] == "17m"
    assert payload["contacts"][0]["dash_levels_detected"] == 2


def test_build_beacon_propagation_summary_uses_median_global_score():
    rows = [
        {
            "slot_start_utc": "2026-05-03T10:00:00+00:00",
            "beacon_callsign": "CS3B",
            "beacon_index": 14,
            "band_name": "20m",
            "detected": True,
            "dash_levels_detected": 3,
            "snr_db_100w": 8.0,
        },
        {
            "slot_start_utc": "2026-05-03T10:10:00+00:00",
            "beacon_callsign": "YV5B",
            "beacon_index": 17,
            "band_name": "17m",
            "detected": False,
            "dash_levels_detected": 0,
            "snr_db_100w": 2.4,
        },
        {
            "slot_start_utc": "2026-05-03T10:20:00+00:00",
            "beacon_callsign": "JA2IGY",
            "beacon_index": 6,
            "band_name": "15m",
            "detected": True,
            "dash_levels_detected": 2,
            "snr_db_100w": 5.0,
        },
    ]

    payload = build_beacon_propagation_summary(rows, window_minutes=60)
    monitored_scores = [entry["score"] for entry in payload["bands"] if entry["events"] > 0]
    weak_band = next(entry for entry in payload["bands"] if entry["band"] == "17m")

    assert payload["kind"] == "beacon"
    assert weak_band["weak_beacons"] == 1
    assert payload["overall"]["score"] == round(median(monitored_scores), 1)


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
    id_len = min(len(template), total_samples)
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
                    "lead_dash_snr_db", "detect_score", "detect_score_gap",
                    "id_threshold_gap", "lead_dash_gap_db", "detected_via",
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

    def test_long_callsign_clean_signal_id_confirmed(self):
        audio = _make_cw_audio("4U1UN", snr_db=30.0)
        result = self._detector("4U1UN").detect(audio)
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

    def test_combined_score_recovers_near_threshold_copy(self):
        score = _combined_detect_score(0.1295, [2.68, 1.81, 0.89, 0.12], 0.18, 3.0)
        assert score >= DETECT_SCORE_THRESHOLD

    def test_combined_score_rewards_ordered_weak_sequence(self):
        score = _combined_detect_score(0.08, [1.8, 1.4, 0.9, 0.6], 0.18, 3.0)
        assert score >= DETECT_SCORE_THRESHOLD

    def test_combined_score_rejects_late_only_spikes(self):
        score = _combined_detect_score(0.1477, [-0.56, -1.26, 4.41, 2.83], 0.18, 3.0)
        assert score < DETECT_SCORE_THRESHOLD

    def test_combined_score_rejects_flat_band_noise(self):
        score = _combined_detect_score(0.0510, [0.55, 0.20, 0.10, 0.0], 0.18, 3.0)
        assert score < DETECT_SCORE_THRESHOLD


class TestBeaconCatalogStatusRules:
    def test_off_air_id_only_detection_is_suppressed(self):
        obs = {
            "detected": True,
            "id_confirmed": False,
            "drift_ms": None,
            "dash_levels_detected": 0,
        }
        apply_catalog_status_rules(obs, "off_air")
        assert obs["detected"] is False
        assert obs["id_confirmed"] is False
        assert obs["drift_ms"] is None

    def test_off_air_dash_detection_is_preserved(self):
        obs = {
            "detected": True,
            "id_confirmed": False,
            "drift_ms": None,
            "dash_levels_detected": 2,
        }
        apply_catalog_status_rules(obs, "off_air")
        assert obs["detected"] is True
        assert obs["dash_levels_detected"] == 2


class TestSchedulerEnvelopeDownsampling:
    def test_exact_factor_downsample_uses_block_mean(self):
        audio = np.arange(8, dtype=np.float32)
        out = _downsample_envelope(audio, src_sr=8, target_sr=2)
        assert np.allclose(out, np.array([1.5, 5.5], dtype=np.float32))

    def test_exact_factor_downsample_trims_partial_tail(self):
        audio = np.arange(10, dtype=np.float32)
        out = _downsample_envelope(audio, src_sr=8, target_sr=2)
        assert len(out) == 2


class _DummyBeaconScheduler:
    def __init__(self, bands):
        self._bands = list(bands)
        self._band_index = 1 if len(self._bands) > 1 else 0
        self._slots_on_band = 7
        self._running = False
        self.start_calls = 0

    async def start(self) -> bool:
        self.start_calls += 1
        self._running = True
        return True

    def snapshot(self) -> dict[str, object]:
        band = self._bands[self._band_index] if self._bands else None
        return {
            "running": self._running,
            "bands": [b.name for b in self._bands],
            "current_band": band.name if band else None,
            "current_freq_hz": band.freq_hz if band else None,
            "slots_on_band": self._slots_on_band,
            "total_slots": 0,
            "total_observations": 0,
            "started_at": None,
            "stopped_at": None,
            "last_error": None,
        }


class TestBeaconApiStartBands:
    @pytest.mark.asyncio
    async def test_start_without_bands_resets_to_all_bands(self, monkeypatch):
        sched = _DummyBeaconScheduler([BANDS[0], BANDS[1]])
        monkeypatch.setattr(beacon_api.state, "beacon_scheduler", sched, raising=False)
        monkeypatch.setattr(beacon_api.state, "scan_engine", None, raising=False)
        monkeypatch.setattr(beacon_api.state, "beacon_iq_queue", None, raising=False)
        monkeypatch.setattr(
            beacon_api,
            "_probe_time_sync",
            lambda: {
                "state": "healthy",
                "can_start": True,
                "reason_code": "ok",
                "message": "Host UTC time validated. Beacon Analysis can start.",
            },
        )

        result = await beacon_api.beacon_start()

        assert result["ok"] is True
        assert result["bands"] == [band.name for band in BANDS]
        assert [band.name for band in sched._bands] == [band.name for band in BANDS]
        assert sched._band_index == 0
        assert sched._slots_on_band == 0

    @pytest.mark.asyncio
    async def test_start_with_explicit_subset_keeps_requested_bands(self, monkeypatch):
        sched = _DummyBeaconScheduler(BANDS)
        monkeypatch.setattr(beacon_api.state, "beacon_scheduler", sched, raising=False)
        monkeypatch.setattr(beacon_api.state, "scan_engine", None, raising=False)
        monkeypatch.setattr(beacon_api.state, "beacon_iq_queue", None, raising=False)
        monkeypatch.setattr(
            beacon_api,
            "_probe_time_sync",
            lambda: {
                "state": "healthy",
                "can_start": True,
                "reason_code": "ok",
                "message": "Host UTC time validated. Beacon Analysis can start.",
            },
        )

        result = await beacon_api.beacon_start(["20m", "17m"])

        assert result["ok"] is True
        assert result["bands"] == ["20m", "17m"]
        assert [band.name for band in sched._bands] == ["20m", "17m"]
        assert sched._band_index == 0
        assert sched._slots_on_band == 0


class TestBeaconTimeSyncGuard:
    def test_classify_time_sync_healthy(self):
        result = beacon_api._classify_time_sync(
            {
                "synchronized": True,
                "ntp_service": "active",
                "server_name": "ntp.ubuntu.com",
                "server_address": "91.189.91.157",
                "offset_ms": 0.175,
                "jitter_ms": 3.006,
                "root_distance_ms": 22.140,
                "leap_status": "normal",
            }
        )

        assert result["state"] == "healthy"
        assert result["can_start"] is True
        assert result["reason_code"] == "ok"

    def test_classify_time_sync_degraded_offset(self):
        result = beacon_api._classify_time_sync(
            {
                "synchronized": True,
                "ntp_service": "active",
                "server_name": "ntp.ubuntu.com",
                "offset_ms": 750.0,
                "root_distance_ms": 22.140,
                "leap_status": "normal",
            }
        )

        assert result["state"] == "degraded"
        assert result["can_start"] is False
        assert result["reason_code"] == "offset_too_high"

    def test_classify_time_sync_offline_not_synchronized(self):
        result = beacon_api._classify_time_sync(
            {
                "synchronized": False,
                "ntp_service": "active",
            }
        )

        assert result["state"] == "offline"
        assert result["can_start"] is False
        assert result["reason_code"] == "not_synchronized"

    @pytest.mark.asyncio
    async def test_beacon_status_includes_time_sync(self, monkeypatch):
        sched = _DummyBeaconScheduler(BANDS)
        monkeypatch.setattr(beacon_api.state, "beacon_scheduler", sched, raising=False)
        monkeypatch.setattr(
            beacon_api,
            "_probe_time_sync",
            lambda: {
                "state": "healthy",
                "can_start": True,
                "reason_code": "ok",
                "message": "Host UTC time validated. Beacon Analysis can start.",
            },
        )

        result = await beacon_api.beacon_status()

        assert result["time_sync"]["state"] == "healthy"
        assert result["time_sync"]["can_start"] is True

    @pytest.mark.asyncio
    async def test_start_blocks_when_time_sync_is_degraded(self, monkeypatch):
        sched = _DummyBeaconScheduler(BANDS)
        monkeypatch.setattr(beacon_api.state, "beacon_scheduler", sched, raising=False)
        monkeypatch.setattr(beacon_api.state, "scan_engine", None, raising=False)
        monkeypatch.setattr(beacon_api.state, "beacon_iq_queue", None, raising=False)
        monkeypatch.setattr(
            beacon_api,
            "_probe_time_sync",
            lambda: {
                "state": "degraded",
                "can_start": False,
                "reason_code": "offset_too_high",
                "message": "Clock offset is degraded for reliable 10-second UTC slots.",
            },
        )

        with pytest.raises(beacon_api.HTTPException) as exc_info:
            await beacon_api.beacon_start()

        assert exc_info.value.status_code == 412
        assert exc_info.value.detail["code"] == "beacon_time_sync_unhealthy"
        assert exc_info.value.detail["time_sync"]["state"] == "degraded"
        assert sched.start_calls == 0

    @pytest.mark.asyncio
    async def test_start_blocks_when_time_sync_is_offline(self, monkeypatch):
        sched = _DummyBeaconScheduler(BANDS)
        monkeypatch.setattr(beacon_api.state, "beacon_scheduler", sched, raising=False)
        monkeypatch.setattr(beacon_api.state, "scan_engine", None, raising=False)
        monkeypatch.setattr(beacon_api.state, "beacon_iq_queue", None, raising=False)
        monkeypatch.setattr(
            beacon_api,
            "_probe_time_sync",
            lambda: {
                "state": "offline",
                "can_start": False,
                "reason_code": "not_synchronized",
                "message": "System clock is not synchronized.",
            },
        )

        with pytest.raises(beacon_api.HTTPException) as exc_info:
            await beacon_api.beacon_start()

        assert exc_info.value.status_code == 412
        assert exc_info.value.detail["time_sync"]["state"] == "offline"
        assert sched.start_calls == 0
