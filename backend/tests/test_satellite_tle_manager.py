# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
Tests for satellite tle_manager badge logic and upsert.
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock


def _make_db(kv=None):
    db = MagicMock()
    db.get_kv = lambda key: (kv or {}).get(key)
    db.set_kv = MagicMock()
    db._lock = __import__("threading").RLock()
    db.conn = MagicMock()
    db.conn.execute = MagicMock(return_value=MagicMock(fetchall=lambda: []))
    db.conn.commit = MagicMock()
    return db


# ── Badge thresholds ────────────────────────────────────────────────────────────

def test_badge_green_fresh():
    from app.satellite.tle_manager import get_tle_badge
    now = datetime.now(timezone.utc)
    fresh = (now - timedelta(days=3)).isoformat()
    db = _make_db({"satellite_tle_last_refresh_ok": fresh})
    badge = get_tle_badge(db)
    assert badge["badge"] == "green"
    assert badge["age_days"] == 3


def test_badge_yellow_medium():
    from app.satellite.tle_manager import get_tle_badge
    now = datetime.now(timezone.utc)
    medium = (now - timedelta(days=10)).isoformat()
    db = _make_db({"satellite_tle_last_refresh_ok": medium})
    badge = get_tle_badge(db)
    assert badge["badge"] == "yellow"


def test_badge_red_stale():
    from app.satellite.tle_manager import get_tle_badge
    now = datetime.now(timezone.utc)
    stale = (now - timedelta(days=25)).isoformat()
    db = _make_db({"satellite_tle_last_refresh_ok": stale})
    badge = get_tle_badge(db)
    assert badge["badge"] == "red"


def test_badge_red_no_key():
    from app.satellite.tle_manager import get_tle_badge
    db = _make_db({})
    badge = get_tle_badge(db)
    assert badge["badge"] == "red"
    assert badge["last_refresh"] is None


def test_badge_boundary_green_7days():
    from app.satellite.tle_manager import get_tle_badge
    now = datetime.now(timezone.utc)
    exactly7 = (now - timedelta(days=7)).isoformat()
    db = _make_db({"satellite_tle_last_refresh_ok": exactly7})
    badge = get_tle_badge(db)
    assert badge["badge"] == "green"


def test_badge_boundary_yellow_8days():
    from app.satellite.tle_manager import get_tle_badge
    now = datetime.now(timezone.utc)
    d8 = (now - timedelta(days=8)).isoformat()
    db = _make_db({"satellite_tle_last_refresh_ok": d8})
    badge = get_tle_badge(db)
    assert badge["badge"] == "yellow"


# ── import_tles_from_bytes ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_import_tles_valid():
    from app.satellite.tle_manager import import_tles_from_bytes
    raw = (
        b"ISS (ZARYA)\n"
        b"1 25544U 98067A   24100.50000000  .00003000  00000-0  60000-4 0  9995\n"
        b"2 25544  51.6400 100.0000 0001234  90.0000 270.0000 15.50000000000012\n"
    )
    db = _make_db()
    result = await import_tles_from_bytes(db, raw)
    assert result["ok"] is True
    assert result["imported"] >= 1


@pytest.mark.asyncio
async def test_import_tles_invalid():
    from app.satellite.tle_manager import import_tles_from_bytes
    db = _make_db()
    result = await import_tles_from_bytes(db, b"garbage data")
    # Either 0 imported (empty) or ok=True with 0 imported — no crash
    assert "ok" in result
