# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
"""Tests for the encrypted persistence layer of mirror plaintext tokens."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.external_mirrors import ExternalMirrorRepository, TokenCache
from app.external_mirrors.token_vault import TokenVault
from app.storage.db import Database


@pytest.fixture
def tmp_db(tmp_path: Path) -> Database:
    return Database(str(tmp_path / "events.sqlite"))


def test_vault_disabled_when_env_unset(monkeypatch):
    monkeypatch.delenv("MIRRORS_MASTER_KEY", raising=False)
    assert TokenVault.from_env() is None


def test_vault_passphrase_roundtrip(monkeypatch):
    monkeypatch.setenv("MIRRORS_MASTER_KEY", "correct-horse-battery-staple")
    vault = TokenVault.from_env()
    assert vault is not None
    ct = vault.encrypt("s3cret")
    assert ct != "s3cret"
    assert vault.decrypt(ct) == "s3cret"


def test_vault_raw_fernet_key_roundtrip(monkeypatch):
    from cryptography.fernet import Fernet

    raw = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("MIRRORS_MASTER_KEY", raw)
    vault = TokenVault.from_env()
    assert vault is not None
    assert vault.decrypt(vault.encrypt("hello")) == "hello"


def test_token_cache_persists_and_reloads(tmp_db, monkeypatch):
    monkeypatch.setenv("MIRRORS_MASTER_KEY", "test-passphrase")
    repo = ExternalMirrorRepository(tmp_db)
    vault = TokenVault.from_env()
    cache = TokenCache(repository=repo, vault=vault)

    result = repo.create(
        name="primary",
        endpoint_url="https://example.org/ingest.php",
        created_by="admin",
    )
    cache.set(result.mirror.id, result.plaintext_token)

    # Simulate restart: brand-new cache, same DB.
    cache2 = TokenCache(repository=repo, vault=vault)
    assert cache2.get(result.mirror.id) is None
    assert cache2.load_persisted() == 1
    assert cache2.get(result.mirror.id) == result.plaintext_token


def test_token_cache_drop_clears_ciphertext(tmp_db, monkeypatch):
    monkeypatch.setenv("MIRRORS_MASTER_KEY", "test-passphrase")
    repo = ExternalMirrorRepository(tmp_db)
    vault = TokenVault.from_env()
    cache = TokenCache(repository=repo, vault=vault)

    result = repo.create(
        name="primary",
        endpoint_url="https://example.org/ingest.php",
        created_by="admin",
    )
    cache.set(result.mirror.id, result.plaintext_token)
    cache.drop(result.mirror.id)

    cache2 = TokenCache(repository=repo, vault=vault)
    assert cache2.load_persisted() == 0


def test_vault_from_data_dir_creates_key_with_0600(tmp_path: Path):
    vault = TokenVault.from_data_dir(tmp_path)
    assert vault is not None
    key_file = tmp_path / ".mirrors_master.key"
    assert key_file.exists()
    mode = key_file.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"
    # Roundtrip works.
    assert vault.decrypt(vault.encrypt("hello")) == "hello"


def test_vault_from_data_dir_reuses_existing_key(tmp_path: Path):
    v1 = TokenVault.from_data_dir(tmp_path)
    assert v1 is not None
    ct = v1.encrypt("payload")
    # Second instantiation must read the same key and decrypt the previous ciphertext.
    v2 = TokenVault.from_data_dir(tmp_path)
    assert v2 is not None
    assert v2.decrypt(ct) == "payload"


def test_token_cache_memory_only_when_no_vault(tmp_db):
    repo = ExternalMirrorRepository(tmp_db)
    cache = TokenCache(repository=repo, vault=None)
    result = repo.create(
        name="primary",
        endpoint_url="https://example.org/ingest.php",
        created_by="admin",
    )
    cache.set(result.mirror.id, result.plaintext_token)
    # Nothing persisted.
    assert repo.iter_token_ciphertexts() == []
    # New cache cannot recover.
    cache2 = TokenCache(repository=repo, vault=None)
    assert cache2.load_persisted() == 0
    assert cache2.get(result.mirror.id) is None
