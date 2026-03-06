# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 17:24:00 UTC

from app.storage.db import Database


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
            "2026-03-06T19:00:00+00:00",
            0.82,
            '{"ssb_state":"SSB_CONFIRMED","ssb_score":0.82,"ssb_parse_method":"direct"}',
        )
    )
    db.insert_callsign(
        _ssb_event(
            "",
            "2026-03-06T19:01:00+00:00",
            0.41,
            '{"ssb_state":"SSB_TRAFFIC","ssb_score":0.41,"ssb_parse_method":"none"}',
        )
    )
    db.insert_callsign(
        _ssb_event(
            "EA1XYZ",
            "2026-03-06T19:02:00+00:00",
            0.76,
            '{"ssb_state":"SSB_CONFIRMED","ssb_score":0.76,"ssb_parse_method":"phonetic"}',
        )
    )

    metrics = db.get_ssb_metrics(window_minutes=1440)

    assert metrics["total_events"] == 3
    assert metrics["by_state"]["SSB_CONFIRMED"] == 2
    assert metrics["by_state"]["SSB_TRAFFIC"] == 1
    assert metrics["confirmed_ratio"] == 0.667
    assert metrics["scores"]["count"] == 3
    assert metrics["scores"]["avg"] == 0.663
    assert metrics["parse_methods"]["direct"] == 1
    assert metrics["parse_methods"]["phonetic"] == 1
    assert metrics["parse_methods"]["none"] == 1


def test_ssb_metrics_fallbacks_when_payload_is_missing(tmp_path):
    db = Database(str(tmp_path / "events.sqlite"))

    db.insert_callsign(_ssb_event("CT2AAA", "2026-03-06T20:00:00+00:00", 0.55, None))
    db.insert_callsign(_ssb_event("", "2026-03-06T20:01:00+00:00", 0.33, None))

    metrics = db.get_ssb_metrics(window_minutes=1440)

    assert metrics["by_state"]["SSB_CONFIRMED"] == 1
    assert metrics["by_state"]["SSB_TRAFFIC"] == 1
    assert metrics["parse_methods"]["unknown"] == 2
    assert metrics["scores"]["count"] == 2
    assert metrics["scores"]["avg"] == 0.44
