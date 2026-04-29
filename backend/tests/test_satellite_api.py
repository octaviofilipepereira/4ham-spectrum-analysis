# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
Integration tests for satellite REST API endpoints.
Uses FastAPI TestClient with mocked state.db.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch, AsyncMock


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_mock_db(installed: bool = True):
    db = MagicMock()
    kv = {
        "satellite_module_installed": "true" if installed else "false",
        "satellite_module_state": "installed" if installed else "idle",
    }
    db.get_kv = lambda k: kv.get(k)
    db.set_kv = MagicMock()
    db.get_settings = MagicMock(return_value={})
    db.save_settings = MagicMock()
    db._lock = __import__("threading").RLock()
    db.conn = MagicMock()
    db.conn.execute = MagicMock(return_value=MagicMock(
        fetchall=lambda: [],
        fetchone=lambda: None,
        rowcount=0,
    ))
    db.conn.commit = MagicMock()
    return db


@pytest.fixture()
def client_installed():
    from app.main import app
    from app.dependencies import state
    state.db = _make_mock_db(installed=True)
    state.auth_enabled = False
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def client_not_installed():
    from app.main import app
    from app.dependencies import state
    state.db = _make_mock_db(installed=False)
    state.auth_enabled = False
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ── /api/satellite/status ──────────────────────────────────────────────────────

def test_status_always_available(client_not_installed):
    with patch("app.satellite.installer.get_status", return_value={"installed": False, "state": "idle"}):
        r = client_not_installed.get("/api/satellite/status")
    assert r.status_code == 200
    assert r.json()["installed"] is False


def test_status_installed(client_installed):
    with patch("app.satellite.installer.get_status", return_value={"installed": True, "state": "installed"}):
        r = client_installed.get("/api/satellite/status")
    assert r.status_code == 200
    assert r.json()["installed"] is True


# ── 503 when not installed ─────────────────────────────────────────────────────

def test_catalog_503_when_not_installed(client_not_installed):
    r = client_not_installed.get("/api/satellite/catalog")
    assert r.status_code == 503
    assert r.json()["detail"] == "not_installed"


def test_passes_503_when_not_installed(client_not_installed):
    r = client_not_installed.get("/api/satellite/passes")
    assert r.status_code == 503


def test_tle_status_503_when_not_installed(client_not_installed):
    r = client_not_installed.get("/api/satellite/tles/status")
    assert r.status_code == 503


# ── passes endpoint ────────────────────────────────────────────────────────────

def test_passes_returns_list_when_installed(client_installed):
    with patch("app.satellite.propagator.get_upcoming_passes", return_value=[]):
        r = client_installed.get("/api/satellite/passes?hours=24")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_passes_bad_hours_422(client_installed):
    r = client_installed.get("/api/satellite/passes?hours=999")
    assert r.status_code == 422


# ── catalog endpoint ───────────────────────────────────────────────────────────

def test_catalog_returns_list(client_installed):
    with patch("app.satellite.catalog_manager.list_catalog", return_value=[]):
        r = client_installed.get("/api/satellite/catalog")
    assert r.status_code == 200
    assert r.json() == []


# ── active pass ────────────────────────────────────────────────────────────────

def test_active_pass_none(client_installed):
    with patch("app.satellite.propagator.get_active_pass", return_value=None):
        r = client_installed.get("/api/satellite/passes/active")
    assert r.status_code == 200
    assert r.json() is None
