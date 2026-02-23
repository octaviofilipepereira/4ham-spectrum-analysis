# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 18:45:00 UTC

from datetime import datetime, timezone

from app.decoders.ft_sync import Ft8SlotTracker


def test_ft8_slot_tracker_locks_track_after_min_hits():
    tracker = Ft8SlotTracker(slot_seconds=15, min_hits=2, freq_tolerance_hz=30.0, max_slots=3)
    now = datetime.now(timezone.utc)

    locked_first = tracker.update(
        now,
        [{"mode": "FT8", "frequency_hz": 14074950, "confidence": 0.82, "snr_db": 18.0}],
    )
    assert locked_first == []

    locked_second = tracker.update(
        now,
        [{"mode": "FT8", "frequency_hz": 14074962, "confidence": 0.88, "snr_db": 21.0}],
    )
    assert len(locked_second) == 1
    assert locked_second[0]["mode"] == "FT8"
    assert locked_second[0]["hits"] >= 2
    assert abs(locked_second[0]["frequency_hz"] - 14074956) <= 12

    snapshot = tracker.snapshot()
    assert snapshot["total_locked"] == 1
    assert snapshot["last_lock_at"] is not None
    assert len(snapshot["last_locked_tracks"]) == 1


def test_ft8_slot_tracker_does_not_merge_modes_on_same_frequency():
    tracker = Ft8SlotTracker(slot_seconds=15, min_hits=2, freq_tolerance_hz=30.0, max_slots=3)
    now = datetime.now(timezone.utc)

    tracker.update(now, [{"mode": "FT8", "frequency_hz": 7074200, "confidence": 0.81, "snr_db": 12.0}])
    tracker.update(now, [{"mode": "FT4", "frequency_hz": 7074204, "confidence": 0.78, "snr_db": 11.0}])

    locked_ft8 = tracker.update(now, [{"mode": "FT8", "frequency_hz": 7074202, "confidence": 0.85, "snr_db": 14.0}])
    locked_ft4 = tracker.update(now, [{"mode": "FT4", "frequency_hz": 7074203, "confidence": 0.83, "snr_db": 13.0}])

    assert len(locked_ft8) == 1
    assert len(locked_ft4) == 1
    assert locked_ft8[0]["mode"] == "FT8"
    assert locked_ft4[0]["mode"] == "FT4"
