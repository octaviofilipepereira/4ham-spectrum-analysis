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
