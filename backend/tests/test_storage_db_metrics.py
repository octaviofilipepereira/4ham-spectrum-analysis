# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 17:24:00 UTC

from datetime import datetime, timezone, timedelta

from app.storage.db import Database


def _now_minus(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _callsign_event(callsign, mode, source, timestamp):
    return {
        "timestamp": timestamp,
        "band": "20m",
        "frequency_hz": 14074000,
        "mode": mode,
        "callsign": callsign,
        "source": source,
        "device": "rtlsdr",
    }


def _ssb_event(callsign, timestamp, confidence, payload):
    return {
        "timestamp": timestamp,
        "band": "20m",
        "frequency_hz": 14255000,
        "mode": "SSB",
        "callsign": callsign,
        "confidence": confidence,
        "payload": payload,
        "source": "asr",
        "device": "rtlsdr",
    }


def _beacon_obs(slot_start_utc, *, detected, id_confirmed=0, dashes=0, snr_db_100w=None):
    return {
        "slot_start_utc": slot_start_utc,
        "slot_index": 14,
        "beacon_callsign": "CS3B",
        "beacon_index": 14,
        "beacon_location": "Madeira, Portugal",
        "beacon_status": "active",
        "band_name": "20m",
        "freq_hz": 14100000,
        "detected": bool(detected),
        "id_confirmed": bool(id_confirmed),
        "id_confidence": 0.0,
        "drift_ms": None,
        "dash_levels_detected": dashes,
        "snr_db_100w": snr_db_100w,
        "snr_db_10w": None,
        "snr_db_1w": None,
        "snr_db_100mw": None,
    }


def test_decoder_baseline_stats_groups_by_source_and_mode(tmp_path):
    db = Database(str(tmp_path / "events.sqlite"))

    db.insert_callsign(_callsign_event("CT1ABC", "FT8", "external_ft", "2026-02-22T17:00:00+00:00"))
    db.insert_callsign(_callsign_event("EA1XYZ", "FT4", "internal_ft", "2026-02-22T17:01:00+00:00"))
    db.insert_callsign(_callsign_event("CT1ABC", "FT8", "external_ft", "2026-02-22T17:02:00+00:00"))

    stats = db.get_decoder_baseline_stats()

    assert stats["callsign_events_total"] == 3
    assert stats["callsign_unique_total"] == 2
    assert stats["by_source"]["external_ft"]["total"] == 2
    assert stats["by_source"]["external_ft"]["unique_callsigns"] == 1
    assert stats["by_source"]["internal_ft"]["total"] == 1
    assert stats["callsign_modes"]["FT8"] == 2
    assert stats["callsign_modes"]["FT4"] == 1


def test_ssb_metrics_aggregates_state_score_and_parse_method(tmp_path):
    db = Database(str(tmp_path / "events.sqlite"))

    db.insert_callsign(
        _ssb_event(
            "CT1ABC",
            _now_minus(30),
            0.82,
            '{"ssb_state":"SSB_CONFIRMED","ssb_score":0.82,"ssb_parse_method":"direct"}',
        )
    )
    db.insert_callsign(
        _ssb_event(
            "",
            _now_minus(20),
            0.41,
            '{"ssb_state":"SSB","ssb_score":0.41,"ssb_parse_method":"none"}',
        )
    )
    db.insert_callsign(
        _ssb_event(
            "EA1XYZ",
            _now_minus(10),
            0.76,
            '{"ssb_state":"SSB_CONFIRMED","ssb_score":0.76,"ssb_parse_method":"phonetic"}',
        )
    )

    metrics = db.get_ssb_metrics(window_minutes=1440)

    assert metrics["total_events"] == 3
    assert metrics["by_state"]["SSB_CONFIRMED"] == 2
    assert metrics["by_state"]["SSB"] == 1
    assert metrics["confirmed_ratio"] == 0.667
    assert metrics["scores"]["count"] == 3
    assert metrics["scores"]["avg"] == 0.663
    assert metrics["parse_methods"]["direct"] == 1
    assert metrics["parse_methods"]["phonetic"] == 1
    assert metrics["parse_methods"]["none"] == 1


def test_ssb_metrics_fallbacks_when_payload_is_missing(tmp_path):
    db = Database(str(tmp_path / "events.sqlite"))

    db.insert_callsign(_ssb_event("CT2AAA", _now_minus(30), 0.55, None))
    db.insert_callsign(_ssb_event("", _now_minus(20), 0.33, None))

    metrics = db.get_ssb_metrics(window_minutes=1440)

    assert metrics["by_state"]["SSB_CONFIRMED"] == 1
    assert metrics["by_state"]["SSB"] == 1
    assert metrics["parse_methods"]["unknown"] == 2
    assert metrics["scores"]["count"] == 2
    assert metrics["scores"]["avg"] == 0.44


def test_beacon_heatmap_keeps_best_pass_fields_from_same_detection(tmp_path):
    db = Database(str(tmp_path / "events.sqlite"))

    best_slot = _now_minus(50)
    latest_slot = _now_minus(10)

    db.insert_beacon_observation(_beacon_obs(_now_minus(70), detected=False, dashes=0, snr_db_100w=-1.2))
    db.insert_beacon_observation(_beacon_obs(best_slot, detected=True, id_confirmed=1, dashes=3, snr_db_100w=1.4))
    db.insert_beacon_observation(_beacon_obs(_now_minus(30), detected=True, id_confirmed=0, dashes=1, snr_db_100w=4.8))
    db.insert_beacon_observation(_beacon_obs(latest_slot, detected=True, id_confirmed=0, dashes=0, snr_db_100w=6.2))

    rows = db.get_beacon_heatmap(hours=2)
    cell = next(r for r in rows if r["beacon_index"] == 14 and r["band_name"] == "20m")

    assert cell["total_slots"] == 4
    assert cell["detections"] == 3
    assert cell["id_confirmed"] == 1
    assert cell["best_dashes"] == 3
    assert cell["best_snr_db"] == 1.4
    assert cell["best_id_confirmed"] == 1
    assert cell["best_detected_utc"] == best_slot
    assert cell["latest_detected_utc"] == latest_slot


def test_beacon_heatmap_returns_null_best_pass_fields_without_detections(tmp_path):
    db = Database(str(tmp_path / "events.sqlite"))

    db.insert_beacon_observation(_beacon_obs(_now_minus(20), detected=False, dashes=0, snr_db_100w=-0.7))

    rows = db.get_beacon_heatmap(hours=2)
    cell = next(r for r in rows if r["beacon_index"] == 14 and r["band_name"] == "20m")

    assert cell["total_slots"] == 1
    assert cell["detections"] == 0
    assert cell["id_confirmed"] == 0
    assert cell["best_dashes"] is None
    assert cell["best_snr_db"] is None
    assert cell["best_id_confirmed"] is None
    assert cell["best_detected_utc"] is None
    assert cell["latest_detected_utc"] is None
