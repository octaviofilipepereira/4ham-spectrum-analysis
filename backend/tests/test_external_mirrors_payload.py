# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
"""Tests for backend.app.external_mirrors.payload."""

from __future__ import annotations

import pytest

from backend.app.external_mirrors.payload import (
    DEFAULT_BATCH_SIZE,
    build_payload,
    has_new_data,
)
from backend.app.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    return Database(str(tmp_path / "events.sqlite"))


def _seed_callsign(db, n=3, base_freq=14_074_000):
    with db._lock:
        for i in range(n):
            db.conn.execute(
                """INSERT INTO callsign_events(timestamp, band, frequency_hz, mode, callsign, snr_db, confidence)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    f"2026-04-22T12:00:{i:02d}Z",
                    "20m",
                    base_freq + i,
                    "FT8",
                    f"CT7TST{i}",
                    10.0,
                    0.9,
                ),
            )
        db.conn.commit()


def _seed_occupancy(db, n=2, base_freq=14_200_000):
    with db._lock:
        for i in range(n):
            db.conn.execute(
                """INSERT INTO occupancy_events(timestamp, band, frequency_hz, bandwidth_hz, power_dbm, occupied)
                   VALUES(?,?,?,?,?,?)""",
                (
                    f"2026-04-22T12:01:{i:02d}Z",
                    "20m",
                    base_freq + i,
                    2700,
                    -90.0,
                    1,
                ),
            )
        db.conn.commit()


def test_build_payload_meta_and_default_scopes(db):
    payload = build_payload(
        db, mirror_name="primary", last_watermark=0, scopes=[]
    )
    meta = payload["meta"]
    assert meta["mirror_name"] == "primary"
    assert meta["previous_watermark"] == 0
    assert meta["new_watermark"] == 0
    assert meta["batch_size"] == DEFAULT_BATCH_SIZE
    assert sorted(meta["scopes"]) == ["callsign_events", "occupancy_events"]
    assert payload["counts"] == {"callsign": 0, "occupancy": 0}


def test_build_payload_returns_events_above_watermark(db):
    _seed_callsign(db, n=5)
    _seed_occupancy(db, n=3)

    payload = build_payload(
        db,
        mirror_name="primary",
        last_watermark=0,
        scopes=["callsign_events", "occupancy_events"],
    )
    assert payload["counts"]["callsign"] == 5
    assert payload["counts"]["occupancy"] == 3
    # Per-table frontier: new_watermark = min(callsign_max, occupancy_max)
    # so the slower table (occupancy=3) is never skipped.
    assert payload["meta"]["new_watermark"] == 3
    cs = payload["events"]["callsign"]
    assert [e["id"] for e in cs] == [1, 2, 3, 4, 5]


def test_build_payload_respects_watermark(db):
    _seed_callsign(db, n=4)
    payload = build_payload(
        db, mirror_name="m", last_watermark=2, scopes=["callsign_events"]
    )
    assert payload["counts"]["callsign"] == 2
    assert [e["id"] for e in payload["events"]["callsign"]] == [3, 4]
    assert payload["meta"]["new_watermark"] == 4


def test_build_payload_scope_filter(db):
    _seed_callsign(db, n=2)
    _seed_occupancy(db, n=2)
    payload = build_payload(
        db, mirror_name="m", last_watermark=0, scopes=["callsign_events"]
    )
    assert payload["counts"]["callsign"] == 2
    assert payload["counts"]["occupancy"] == 0
    assert payload["events"]["occupancy"] == []


def test_build_payload_batch_size_caps_results(db):
    _seed_callsign(db, n=10)
    payload = build_payload(
        db,
        mirror_name="m",
        last_watermark=0,
        scopes=["callsign_events"],
        batch_size=3,
    )
    assert payload["counts"]["callsign"] == 3
    assert payload["meta"]["new_watermark"] == 3


def test_has_new_data():
    assert has_new_data({"counts": {"callsign": 0, "occupancy": 1}}) is True
    assert has_new_data({"counts": {"callsign": 0, "occupancy": 0}}) is False
    assert has_new_data({}) is False


def test_build_payload_unknown_table_rejected(db):
    # Indirectly: scopes only filter known tables, so an unknown scope is silently
    # ignored. The internal helper rejects unknown tables.
    from backend.app.external_mirrors.payload import _fetch_events_since

    with pytest.raises(ValueError):
        _fetch_events_since(db, "evil_table", 0, 10)
