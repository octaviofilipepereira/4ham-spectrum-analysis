# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
Tests for satellite propagator: pass computation with mocked pyorbital.
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


def _make_db(settings=None, kv=None):
    db = MagicMock()
    _kv = kv or {}
    _settings = settings or {"station": {"lat": 38.72, "lon": -9.14, "alt": 50.0}}
    db.get_kv = lambda key: _kv.get(key)
    db.get_settings = MagicMock(return_value=_settings)
    db._lock = __import__("threading").RLock()
    db.conn = MagicMock()
    db.conn.execute = MagicMock(return_value=MagicMock(
        fetchall=lambda: [],
        fetchone=lambda: None,
    ))
    db.conn.commit = MagicMock()
    return db


def _mock_pass_tuple():
    """Return a fake pyorbital pass tuple: (aos_utc, los_utc, max_elevation)."""
    from datetime import timezone, timedelta
    now = datetime.now(timezone.utc)
    aos = now
    los = now + __import__("datetime").timedelta(minutes=10)
    return (aos, los, 30.0)


# ── compute_passes ─────────────────────────────────────────────────────────────

def test_compute_passes_returns_list():
    from app.satellite.propagator import compute_passes

    fake_orbital_instance = MagicMock()
    fake_orbital_instance.get_next_passes = MagicMock(return_value=[_mock_pass_tuple()])
    fake_orbital_class = MagicMock(return_value=fake_orbital_instance)
    fake_pyorbital = MagicMock()
    fake_pyorbital.Orbital = fake_orbital_class

    db = _make_db()
    fake_row = {
        "name": "ISS",
        "tle_line1": "1 25544U 98067A   24100.50000000  .00003000  00000-0  60000-4 0  9995",
        "tle_line2": "2 25544  51.6400 100.0000 0001234  90.0000 270.0000 15.50000000000012",
        "tle_epoch": None,
        "min_elevation_deg": 5.0,
    }
    db.conn.execute.return_value.fetchone = lambda: fake_row

    with patch("app.satellite.propagator._lazy_pyorbital", return_value=fake_pyorbital):
        result = compute_passes(db, norad_id=25544, lat=38.72, lon=-9.14, alt=50.0, hours=24)

    assert isinstance(result, list)
    assert len(result) >= 1


def test_compute_passes_no_tle_raises():
    from app.satellite.propagator import compute_passes

    db = _make_db()
    db.conn.execute.return_value.fetchone = lambda: None

    fake_pyorbital = MagicMock()
    with patch("app.satellite.propagator._lazy_pyorbital", return_value=fake_pyorbital):
        with pytest.raises(RuntimeError, match="No TLE"):
            compute_passes(db, norad_id=99999, lat=38.72, lon=-9.14, alt=50.0)


# ── get_active_pass ────────────────────────────────────────────────────────────

def test_get_active_pass_none_when_no_passes():
    from app.satellite.propagator import get_active_pass
    db = _make_db()
    db.conn.execute.return_value.fetchone = lambda: None
    result = get_active_pass(db)
    assert result is None


# ── get_upcoming_passes ────────────────────────────────────────────────────────

def test_get_upcoming_passes_returns_list():
    from app.satellite.propagator import get_upcoming_passes
    db = _make_db()
    db.conn.execute.return_value.fetchall = lambda: []
    result = get_upcoming_passes(db, hours=6)
    assert isinstance(result, list)
