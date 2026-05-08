# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
Tests for satellite installer: KV state machine, is_installed, get_status.
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


def _make_db(kv=None):
    db = MagicMock()
    _kv = dict(kv or {})
    db.get_kv = lambda key: _kv.get(key)
    db.set_kv = lambda key, val: _kv.update({key: val})
    db._lock = __import__("threading").RLock()
    db.conn = MagicMock()
    db.conn.execute = MagicMock(return_value=MagicMock(fetchall=lambda: []))
    db.conn.commit = MagicMock()
    return db


# ── is_installed ───────────────────────────────────────────────────────────────

def test_is_installed_false_when_no_kv():
    from app.satellite.installer import is_installed
    db = _make_db({})
    assert is_installed(db) is False


def test_is_installed_true_when_kv_set():
    from app.satellite.installer import is_installed
    db = _make_db({"satellite_module_installed": "true"})
    assert is_installed(db) is True


# ── get_status ─────────────────────────────────────────────────────────────────

def test_get_status_not_installed():
    from app.satellite.installer import get_status
    db = _make_db({})
    status = get_status(db)
    assert status["installed"] is False
    assert "state" in status


def test_get_status_installed():
    from app.satellite.installer import get_status
    db = _make_db({
        "satellite_module_installed": "true",
        "satellite_module_state": "installed",
        "satellite_module_schema_version": "1",
    })
    status = get_status(db)
    assert status["installed"] is True
    assert status["state"] == "installed"


# ── get_job_status ─────────────────────────────────────────────────────────────

def test_get_job_status_missing_returns_none():
    from app.satellite.installer import get_job_status
    db = _make_db({})
    result = get_job_status(db, "non-existent-uuid")
    assert result is None


def test_get_job_status_present():
    from app.satellite.installer import get_job_status
    job_id = "test-job-123"
    db = _make_db({
        f"satellite_install_job_{job_id}_state": "running",
        f"satellite_install_job_{job_id}_log": "Installing...",
        f"satellite_install_job_{job_id}_started_at": "2026-01-01T00:00:00",
    })
    result = get_job_status(db, job_id)
    assert result is not None
    assert result["state"] == "running"
    assert result["log"] == "Installing..."


# ── install raises RuntimeError if already installing ─────────────────────────

@pytest.mark.asyncio
async def test_install_raises_if_already_installing():
    from app.satellite.installer import install
    db = _make_db({
        "satellite_module_state": "installing",
        "satellite_module_installed": "false",
    })
    with pytest.raises(RuntimeError, match="already"):
        await install(db)
