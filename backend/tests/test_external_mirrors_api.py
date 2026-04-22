# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
"""End-to-end tests for backend.app.api.external_mirrors."""

from __future__ import annotations

import base64
import os

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def auth_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_REQUIRED", "1")
    monkeypatch.setenv("BASIC_AUTH_USER", "admin")
    monkeypatch.setenv("BASIC_AUTH_PASS", "secret")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "events.sqlite"))
    monkeypatch.setenv("PREVIEW_AUTOSTART", "0")
    # Force state to current values regardless of import order in other tests.
    from backend.app.dependencies import state as st
    monkeypatch.setattr(st, "auth_user", "admin", raising=False)
    monkeypatch.setattr(st, "auth_pass", "secret", raising=False)
    monkeypatch.setattr(st, "auth_pass_is_hashed", False, raising=False)
    monkeypatch.setattr(st, "auth_required", True, raising=False)
    # Same module under the bare 'app' path used by routers.
    try:
        from app.dependencies import state as st_alt
        monkeypatch.setattr(st_alt, "auth_user", "admin", raising=False)
        monkeypatch.setattr(st_alt, "auth_pass", "secret", raising=False)
        monkeypatch.setattr(st_alt, "auth_pass_is_hashed", False, raising=False)
        monkeypatch.setattr(st_alt, "auth_required", True, raising=False)
    except ImportError:
        pass
    yield


@pytest.fixture()
def app(auth_env):
    """Build a minimal FastAPI app exposing only the mirrors router."""
    # IMPORTANT: import via the bare 'app' package so we share the same
    # module instances as the router (which uses 'from app.external_mirrors ...').
    from app.api import external_mirrors as ext_router
    from app.dependencies import state as st
    from app.external_mirrors import (
        ExternalMirrorPusher,
        ExternalMirrorRepository,
        TokenCache,
    )
    from app.external_mirrors import registry as mirrors_registry

    repo = ExternalMirrorRepository(st.db)
    # Clean slate for each test (state.db may be shared across tests in the session).
    with st.db._lock:
        st.db.conn.execute("DELETE FROM external_mirror_audit")
        st.db.conn.execute("DELETE FROM external_mirrors")
        st.db.conn.commit()
    cache = TokenCache()
    pusher = ExternalMirrorPusher(repo=repo, token_cache=cache)
    mirrors_registry.init(repo, pusher, cache)

    fastapi_app = FastAPI()
    fastapi_app.include_router(
        ext_router.router, prefix="/api/admin/mirrors", tags=["External Mirrors"]
    )
    return fastapi_app


@pytest.fixture()
def client(app):
    return TestClient(app)


def _basic(user="admin", pwd="secret"):
    raw = f"{user}:{pwd}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------

def test_requires_auth(client):
    r = client.get("/api/admin/mirrors")
    assert r.status_code == 401


def test_rejects_wrong_password(client):
    r = client.get("/api/admin/mirrors", headers=_basic(pwd="bad"))
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Lifecycle: create → list → get → update → rotate → audit → delete
# ---------------------------------------------------------------------------

def test_full_lifecycle(client):
    # Initially empty.
    r = client.get("/api/admin/mirrors", headers=_basic())
    assert r.status_code == 200
    assert r.json() == {"mirrors": []}

    # Create.
    r = client.post(
        "/api/admin/mirrors",
        json={
            "name": "primary",
            "endpoint_url": "https://mirror.example.com/ingest.php",
            "data_scopes": ["callsign_events"],
            "push_interval_seconds": 300,
        },
        headers=_basic(),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["mirror"]["name"] == "primary"
    assert "auth_token_hash" not in body["mirror"]
    token = body["plaintext_token"]
    assert len(token) >= 32
    mirror_id = body["mirror"]["id"]

    # Get.
    r = client.get(f"/api/admin/mirrors/{mirror_id}", headers=_basic())
    assert r.status_code == 200
    assert r.json()["mirror"]["id"] == mirror_id

    # Update.
    r = client.patch(
        f"/api/admin/mirrors/{mirror_id}",
        json={"push_interval_seconds": 600},
        headers=_basic(),
    )
    assert r.status_code == 200
    assert r.json()["mirror"]["push_interval_seconds"] == 600

    # Disable then enable.
    r = client.post(f"/api/admin/mirrors/{mirror_id}/disable", headers=_basic())
    assert r.status_code == 200
    assert r.json()["mirror"]["enabled"] is False
    r = client.post(f"/api/admin/mirrors/{mirror_id}/enable", headers=_basic())
    assert r.status_code == 200
    assert r.json()["mirror"]["enabled"] is True

    # Rotate token.
    r = client.post(f"/api/admin/mirrors/{mirror_id}/rotate-token", headers=_basic())
    assert r.status_code == 200
    new_token = r.json()["plaintext_token"]
    assert new_token != token

    # Audit log has multiple events.
    r = client.get(f"/api/admin/mirrors/{mirror_id}/audit", headers=_basic())
    assert r.status_code == 200
    events = [a["event"] for a in r.json()["audit"]]
    assert "created" in events
    assert "updated" in events
    assert "token_rotated" in events
    assert "enabled" in events
    assert "disabled" in events

    # Delete.
    r = client.delete(f"/api/admin/mirrors/{mirror_id}", headers=_basic())
    assert r.status_code == 200
    assert r.json()["deleted"] is True

    # Now 404.
    r = client.get(f"/api/admin/mirrors/{mirror_id}", headers=_basic())
    assert r.status_code == 404


def test_create_conflict(client):
    payload = {
        "name": "dup",
        "endpoint_url": "https://x/ingest.php",
    }
    assert client.post("/api/admin/mirrors", json=payload, headers=_basic()).status_code == 201
    r = client.post("/api/admin/mirrors", json=payload, headers=_basic())
    assert r.status_code == 409


def test_create_validates_required(client):
    r = client.post(
        "/api/admin/mirrors",
        json={"name": "", "endpoint_url": ""},
        headers=_basic(),
    )
    assert r.status_code == 400


def test_test_endpoint_requires_cached_token(client, monkeypatch):
    r = client.post(
        "/api/admin/mirrors",
        json={"name": "tt", "endpoint_url": "https://example.com/ingest.php"},
        headers=_basic(),
    )
    mirror_id = r.json()["mirror"]["id"]

    # Drop the cached token.
    from app.external_mirrors import registry as mirrors_registry
    mirrors_registry.get_token_cache().drop(mirror_id)

    r = client.post(f"/api/admin/mirrors/{mirror_id}/test", headers=_basic())
    assert r.status_code == 409
