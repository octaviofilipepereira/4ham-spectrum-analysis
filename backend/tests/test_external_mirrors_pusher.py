# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
"""Tests for backend.app.external_mirrors.pusher."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx
import pytest

from backend.app.external_mirrors.http_client import MirrorHttpClient
from backend.app.external_mirrors.pusher import (
    DEFAULT_TICK_SECONDS,
    ExternalMirrorPusher,
    TokenCache,
)
from backend.app.external_mirrors.repository import ExternalMirrorRepository
from backend.app.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    return Database(str(tmp_path / "events.sqlite"))


@pytest.fixture()
def repo(db):
    return ExternalMirrorRepository(db)


def _seed_one_event(db):
    with db._lock:
        db.conn.execute(
            """INSERT INTO callsign_events(timestamp, band, frequency_hz, mode, callsign, snr_db, confidence)
               VALUES(?,?,?,?,?,?,?)""",
            ("2026-04-22T12:00:00Z", "20m", 14_074_000, "FT8", "CT7TEST", 10.0, 0.9),
        )
        db.conn.commit()


def _make_client(handler):
    return MirrorHttpClient(
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,
        backoff_base_seconds=0.0,
        backoff_cap_seconds=0.0,
    )


def test_token_cache_basic():
    c = TokenCache()
    c.set(1, "abc")
    assert c.get(1) == "abc"
    assert c.get(2) is None
    c.drop(1)
    assert c.get(1) is None


@pytest.mark.asyncio
async def test_pusher_skips_when_token_missing(db, repo):
    result = repo.create(
        name="m1",
        endpoint_url="https://x/ingest.php",
        created_by="admin",
        push_interval_seconds=10,
        data_scopes=["callsign_events"],
    )
    # Do NOT register the plaintext token in the cache.
    cache = TokenCache()

    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, text="ok")

    pusher = ExternalMirrorPusher(
        repo=repo,
        token_cache=cache,
        http_client=_make_client(handler),
        tick_seconds=0.1,
    )
    await pusher._tick_once()
    assert calls == []
    audit = repo.list_audit(result.mirror.id)
    assert any(a["event"] == "skipped_no_token" for a in audit)


@pytest.mark.asyncio
async def test_pusher_pushes_and_updates_watermark(db, repo):
    result = repo.create(
        name="m1",
        endpoint_url="https://x/ingest.php",
        created_by="admin",
        push_interval_seconds=10,
        data_scopes=["callsign_events"],
    )
    _seed_one_event(db)
    cache = TokenCache()
    cache.set(result.mirror.id, result.plaintext_token)

    captured: Dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, text='{"ok":1}')

    pusher = ExternalMirrorPusher(
        repo=repo,
        token_cache=cache,
        http_client=_make_client(handler),
        tick_seconds=0.1,
    )
    await pusher._tick_once()

    # Bookkeeping updated.
    after = repo.get(result.mirror.id)
    assert after.last_push_status == "ok"
    assert after.last_push_watermark == 1
    assert after.consecutive_failures == 0
    assert after.last_push_at is not None
    assert b'"callsign"' in captured["body"]
    assert "x-4ham-signature" in captured["headers"]


@pytest.mark.asyncio
async def test_pusher_records_failure_and_increments(db, repo):
    result = repo.create(
        name="m1",
        endpoint_url="https://x/ingest.php",
        created_by="admin",
        push_interval_seconds=10,
        data_scopes=["callsign_events"],
    )
    cache = TokenCache()
    cache.set(result.mirror.id, result.plaintext_token)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    pusher = ExternalMirrorPusher(
        repo=repo,
        token_cache=cache,
        http_client=_make_client(handler),
        tick_seconds=0.1,
    )
    await pusher._tick_once()
    after = repo.get(result.mirror.id)
    assert after.consecutive_failures == 1
    assert after.last_push_status and after.last_push_status.startswith("error")
    assert after.last_push_watermark == 0


@pytest.mark.asyncio
async def test_pusher_skips_disabled_mirrors(db, repo):
    result = repo.create(
        name="m1",
        endpoint_url="https://x/ingest.php",
        created_by="admin",
        push_interval_seconds=10,
        data_scopes=["callsign_events"],
        enabled=False,
    )
    cache = TokenCache()
    cache.set(result.mirror.id, result.plaintext_token)

    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, text="ok")

    pusher = ExternalMirrorPusher(
        repo=repo,
        token_cache=cache,
        http_client=_make_client(handler),
        tick_seconds=0.1,
    )
    await pusher._tick_once()
    assert calls == []


@pytest.mark.asyncio
async def test_pusher_respects_push_interval(db, repo, monkeypatch):
    result = repo.create(
        name="m1",
        endpoint_url="https://x/ingest.php",
        created_by="admin",
        push_interval_seconds=300,
        data_scopes=["callsign_events"],
    )
    # Mark a recent push so the mirror is NOT due.
    repo.update_after_push(result.mirror.id, success=True, watermark=0, status_msg="ok")
    cache = TokenCache()
    cache.set(result.mirror.id, result.plaintext_token)

    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, text="ok")

    pusher = ExternalMirrorPusher(
        repo=repo,
        token_cache=cache,
        http_client=_make_client(handler),
        tick_seconds=0.1,
    )
    await pusher._tick_once()
    assert calls == []  # not yet due


@pytest.mark.asyncio
async def test_pusher_start_stop_lifecycle(db, repo):
    result = repo.create(
        name="m1",
        endpoint_url="https://x/ingest.php",
        created_by="admin",
        push_interval_seconds=10,
        data_scopes=["callsign_events"],
    )
    cache = TokenCache()
    cache.set(result.mirror.id, result.plaintext_token)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    pusher = ExternalMirrorPusher(
        repo=repo,
        token_cache=cache,
        http_client=_make_client(handler),
        tick_seconds=0.05,
    )
    await pusher.start()
    assert pusher.running
    # Allow at least one tick to run.
    await asyncio.sleep(0.15)
    await pusher.stop()
    assert not pusher.running
    after = repo.get(result.mirror.id)
    assert after.last_push_at is not None
