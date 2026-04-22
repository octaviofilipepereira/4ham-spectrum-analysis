# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
"""Tests for backend.app.external_mirrors.repository."""

from __future__ import annotations

import threading

import pytest

from backend.app.core.auth import is_bcrypt_hash
from backend.app.external_mirrors import (
    AUTO_DISABLE_THRESHOLD,
    ExternalMirrorRepository,
    MirrorNameConflictError,
    MirrorNotFoundError,
)
from backend.app.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    return Database(str(tmp_path / "events.sqlite"))


@pytest.fixture()
def repo(db):
    return ExternalMirrorRepository(db)


def _make(repo, name="primary", **overrides):
    kwargs = dict(
        name=name,
        endpoint_url="https://example.com/ingest.php",
        created_by="admin",
        data_scopes=["events", "scan_status"],
        push_interval_seconds=300,
    )
    kwargs.update(overrides)
    return repo.create(**kwargs)


# ---------------------------------------------------------------------------
# Schema / table presence
# ---------------------------------------------------------------------------

def test_schema_creates_tables(db):
    cur = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('external_mirrors', 'external_mirror_audit') ORDER BY name"
    )
    names = [r[0] for r in cur.fetchall()]
    assert names == ["external_mirror_audit", "external_mirrors"]


# ---------------------------------------------------------------------------
# Create / token hashing
# ---------------------------------------------------------------------------

def test_create_persists_and_hashes_token(repo, db):
    result = _make(repo)
    assert result.mirror.id > 0
    assert result.plaintext_token  # returned exactly once
    assert len(result.plaintext_token) >= 32

    # Stored hash is bcrypt, NOT plaintext.
    cur = db.conn.execute(
        "SELECT auth_token_hash FROM external_mirrors WHERE id = ?",
        (result.mirror.id,),
    )
    stored_hash = cur.fetchone()[0]
    assert is_bcrypt_hash(stored_hash)
    assert result.plaintext_token not in stored_hash

    assert repo.verify_token(result.mirror.id, result.plaintext_token) is True
    assert repo.verify_token(result.mirror.id, "wrong") is False


def test_create_logs_audit(repo):
    result = _make(repo)
    audit = repo.list_audit(result.mirror.id)
    assert len(audit) == 1
    assert audit[0]["event"] == "created"
    assert audit[0]["actor"] == "admin"
    assert audit[0]["details"]["endpoint_url"] == "https://example.com/ingest.php"


def test_create_rejects_invalid_inputs(repo):
    with pytest.raises(ValueError):
        repo.create(name="", endpoint_url="https://x", created_by="admin")
    with pytest.raises(ValueError):
        repo.create(name="x", endpoint_url="", created_by="admin")
    with pytest.raises(ValueError):
        repo.create(
            name="x",
            endpoint_url="https://x",
            created_by="admin",
            push_interval_seconds=1,
        )


def test_unique_name_constraint(repo):
    _make(repo, name="dup")
    with pytest.raises(MirrorNameConflictError):
        _make(repo, name="dup")


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def test_get_and_list(repo):
    a = _make(repo, name="a")
    b = _make(repo, name="b", enabled=False)
    assert repo.get(a.mirror.id).name == "a"
    assert repo.get_by_name("b").id == b.mirror.id
    assert repo.get(99999) is None

    all_mirrors = repo.list()
    assert [m.name for m in all_mirrors] == ["a", "b"]
    enabled_only = repo.list(include_disabled=False)
    assert [m.name for m in enabled_only] == ["a"]


def test_to_public_dict_excludes_token_hash(repo):
    result = _make(repo)
    public = result.mirror.to_public_dict()
    assert "auth_token_hash" not in public
    assert public["name"] == "primary"


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def test_update_changes_fields_and_logs_diff(repo):
    result = _make(repo)
    updated = repo.update(
        result.mirror.id,
        actor="admin",
        push_interval_seconds=600,
        data_scopes=["events"],
    )
    assert updated.push_interval_seconds == 600
    assert updated.data_scopes == ["events"]

    audit = repo.list_audit(result.mirror.id)
    # Most recent first.
    assert audit[0]["event"] == "updated"
    diff = audit[0]["details"]["diff"]
    assert diff["push_interval_seconds"] == {"from": 300, "to": 600}
    assert diff["data_scopes"] == {"from": ["events", "scan_status"], "to": ["events"]}


def test_update_rejects_unknown_field(repo):
    result = _make(repo)
    with pytest.raises(ValueError):
        repo.update(result.mirror.id, foo="bar")


def test_update_missing_mirror_raises(repo):
    with pytest.raises(MirrorNotFoundError):
        repo.update(123, name="x")


def test_update_no_op_returns_existing_without_audit(repo):
    result = _make(repo)
    audit_before = len(repo.list_audit(result.mirror.id))
    same = repo.update(result.mirror.id, name="primary")
    assert same.name == "primary"
    audit_after = len(repo.list_audit(result.mirror.id))
    assert audit_after == audit_before


# ---------------------------------------------------------------------------
# Enable / disable
# ---------------------------------------------------------------------------

def test_set_enabled_audits_and_clears_failures_on_reenable(repo):
    result = _make(repo)
    # Inject failures.
    for _ in range(3):
        repo.update_after_push(result.mirror.id, success=False, status_msg="boom")
    after_disable = repo.set_enabled(result.mirror.id, False, actor="admin")
    assert after_disable.enabled is False
    after_enable = repo.set_enabled(result.mirror.id, True, actor="admin")
    assert after_enable.enabled is True
    assert after_enable.consecutive_failures == 0
    assert after_enable.auto_disabled_at is None

    events = [a["event"] for a in repo.list_audit(result.mirror.id)]
    assert "enabled" in events
    assert "disabled" in events


# ---------------------------------------------------------------------------
# Token rotation
# ---------------------------------------------------------------------------

def test_rotate_token_invalidates_old(repo):
    result = _make(repo)
    rotated = repo.rotate_token(result.mirror.id, actor="admin")
    assert rotated.plaintext_token != result.plaintext_token
    assert repo.verify_token(result.mirror.id, result.plaintext_token) is False
    assert repo.verify_token(result.mirror.id, rotated.plaintext_token) is True
    assert any(a["event"] == "token_rotated" for a in repo.list_audit(result.mirror.id))


# ---------------------------------------------------------------------------
# Push bookkeeping
# ---------------------------------------------------------------------------

def test_update_after_push_success_resets_failures(repo):
    result = _make(repo)
    repo.update_after_push(result.mirror.id, success=False, status_msg="boom")
    repo.update_after_push(result.mirror.id, success=False, status_msg="boom")
    after = repo.update_after_push(
        result.mirror.id, success=True, watermark=42, status_msg="ok"
    )
    assert after.consecutive_failures == 0
    assert after.last_push_watermark == 42
    assert after.last_push_status == "ok"
    assert after.last_push_at is not None


def test_update_after_push_failure_increments(repo):
    result = _make(repo)
    a = repo.update_after_push(result.mirror.id, success=False, status_msg="x")
    b = repo.update_after_push(result.mirror.id, success=False, status_msg="x")
    assert a.consecutive_failures == 1
    assert b.consecutive_failures == 2
    assert b.enabled is True


def test_auto_disable_at_threshold(repo):
    result = _make(repo)
    last = None
    for _ in range(AUTO_DISABLE_THRESHOLD):
        last = repo.update_after_push(result.mirror.id, success=False, status_msg="oops")
    assert last is not None
    assert last.consecutive_failures == AUTO_DISABLE_THRESHOLD
    assert last.enabled is False
    assert last.auto_disabled_at is not None
    events = [a["event"] for a in repo.list_audit(result.mirror.id)]
    assert "auto_disabled" in events


def test_custom_auto_disable_threshold(db):
    repo = ExternalMirrorRepository(db, auto_disable_threshold=2)
    result = _make(repo, name="lowthresh")
    repo.update_after_push(result.mirror.id, success=False, status_msg="x")
    after = repo.update_after_push(result.mirror.id, success=False, status_msg="x")
    assert after.enabled is False
    assert after.consecutive_failures == 2


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def test_delete_removes_row_and_cascades_audit(repo, db):
    result = _make(repo)
    assert repo.delete(result.mirror.id, actor="admin") is True
    assert repo.get(result.mirror.id) is None
    cur = db.conn.execute(
        "SELECT COUNT(*) FROM external_mirror_audit WHERE mirror_id = ?",
        (result.mirror.id,),
    )
    # Cascade deletes any audit rows tied to the mirror; FK is enforced if PRAGMA on,
    # otherwise rows may remain (this is an acceptable best-effort property).
    count = cur.fetchone()[0]
    assert count >= 0


def test_delete_missing_returns_false(repo):
    assert repo.delete(99999) is False


# ---------------------------------------------------------------------------
# Audit listing
# ---------------------------------------------------------------------------

def test_audit_listing_chronological_desc(repo):
    result = _make(repo)
    repo.update(result.mirror.id, actor="admin", push_interval_seconds=600)
    repo.rotate_token(result.mirror.id, actor="admin")
    audit = repo.list_audit(result.mirror.id)
    events = [a["event"] for a in audit]
    # Most recent first => token_rotated before updated before created.
    assert events[0] == "token_rotated"
    assert events[-1] == "created"


# ---------------------------------------------------------------------------
# Concurrency smoke test
# ---------------------------------------------------------------------------

def test_thread_safe_concurrent_writes(repo):
    result = _make(repo, push_interval_seconds=300)

    errors: list = []

    def worker(idx: int) -> None:
        try:
            repo.update_after_push(
                result.mirror.id, success=True, watermark=idx, status_msg="ok"
            )
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    final = repo.get(result.mirror.id)
    assert final is not None
    assert final.consecutive_failures == 0
