# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
"""
Repository for external mirror configurations and audit log.

Stores remote PHP/MySQL push targets to which the local backend mirrors
dashboard-relevant data. Auth tokens are bcrypt-hashed at rest and only
returned in plaintext once on creation/rotation.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from ..core.auth import (
    generate_secure_token,
    hash_password,
    is_bcrypt_hash,
    verify_password,
)
from ..storage.db import Database


AUTO_DISABLE_THRESHOLD = 5
DEFAULT_TOKEN_BYTES = 32


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class MirrorNotFoundError(LookupError):
    """Raised when a mirror id/name does not exist."""


class MirrorNameConflictError(ValueError):
    """Raised when an attempt is made to create/rename a mirror with a duplicate name."""


@dataclass
class ExternalMirror:
    id: int
    name: str
    endpoint_url: str
    auth_token_hash: str
    enabled: bool
    push_interval_seconds: int
    data_scopes: List[str]
    retention_days: Optional[int]
    last_push_at: Optional[str]
    last_push_status: Optional[str]
    last_push_watermark: int
    consecutive_failures: int
    auto_disabled_at: Optional[str]
    created_at: str
    created_by: str
    updated_at: Optional[str]

    def to_public_dict(self) -> Dict[str, Any]:
        """Serialise excluding the auth token hash."""
        d = asdict(self)
        d.pop("auth_token_hash", None)
        return d


def _row_to_mirror(row: sqlite3.Row) -> ExternalMirror:
    try:
        scopes = json.loads(row["data_scopes"]) if row["data_scopes"] else []
        if not isinstance(scopes, list):
            scopes = []
    except (json.JSONDecodeError, TypeError):
        scopes = []
    return ExternalMirror(
        id=int(row["id"]),
        name=row["name"],
        endpoint_url=row["endpoint_url"],
        auth_token_hash=row["auth_token_hash"],
        enabled=bool(row["enabled"]),
        push_interval_seconds=int(row["push_interval_seconds"]),
        data_scopes=scopes,
        retention_days=row["retention_days"] if row["retention_days"] is not None else None,
        last_push_at=row["last_push_at"],
        last_push_status=row["last_push_status"],
        last_push_watermark=int(row["last_push_watermark"] or 0),
        consecutive_failures=int(row["consecutive_failures"] or 0),
        auto_disabled_at=row["auto_disabled_at"],
        created_at=row["created_at"],
        created_by=row["created_by"],
        updated_at=row["updated_at"],
    )


@dataclass
class CreateMirrorResult:
    mirror: ExternalMirror
    plaintext_token: str


@dataclass
class RotateTokenResult:
    mirror: ExternalMirror
    plaintext_token: str


class ExternalMirrorRepository:
    """
    CRUD + audit for external mirror configurations.

    All mutating operations append a row to ``external_mirror_audit``.
    Tokens are bcrypt-hashed; plaintext tokens are returned ONCE on
    create / rotate_token and never persisted.
    """

    AUDIT_THRESHOLD = AUTO_DISABLE_THRESHOLD

    def __init__(self, db: Database, *, auto_disable_threshold: int = AUTO_DISABLE_THRESHOLD):
        self._db = db
        self._conn = db.conn
        self._lock = db._lock
        self._auto_disable_threshold = max(1, int(auto_disable_threshold))

    # ------------------------------------------------------------------
    # Audit helpers
    # ------------------------------------------------------------------
    def log_event(
        self,
        mirror_id: int,
        event: str,
        actor: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        details_json = json.dumps(details, sort_keys=True, default=str) if details else None
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO external_mirror_audit(mirror_id, ts, event, actor, details)
                VALUES (?, ?, ?, ?, ?)
                """,
                (mirror_id, _utcnow_iso(), event, actor, details_json),
            )
            self._conn.commit()

    def list_audit(self, mirror_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT id, mirror_id, ts, event, actor, details
                FROM external_mirror_audit
                WHERE mirror_id = ?
                ORDER BY ts DESC, id DESC
                LIMIT ?
                """,
                (mirror_id, limit),
            )
            rows = cur.fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            details = None
            if r["details"]:
                try:
                    details = json.loads(r["details"])
                except json.JSONDecodeError:
                    details = {"_raw": r["details"]}
            out.append(
                {
                    "id": int(r["id"]),
                    "mirror_id": int(r["mirror_id"]),
                    "ts": r["ts"],
                    "event": r["event"],
                    "actor": r["actor"],
                    "details": details,
                }
            )
        return out

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def create(
        self,
        *,
        name: str,
        endpoint_url: str,
        created_by: str,
        plaintext_token: Optional[str] = None,
        push_interval_seconds: int = 300,
        data_scopes: Optional[Iterable[str]] = None,
        retention_days: Optional[int] = None,
        enabled: bool = True,
    ) -> CreateMirrorResult:
        name = (name or "").strip()
        endpoint_url = (endpoint_url or "").strip()
        if not name:
            raise ValueError("name is required")
        if not endpoint_url:
            raise ValueError("endpoint_url is required")
        if push_interval_seconds < 10:
            raise ValueError("push_interval_seconds must be >= 10")

        scopes_list = list(data_scopes) if data_scopes else []
        scopes_json = json.dumps(scopes_list)
        token = plaintext_token or generate_secure_token(DEFAULT_TOKEN_BYTES)
        token_hash = hash_password(token)
        now = _utcnow_iso()

        with self._lock:
            try:
                cur = self._conn.execute(
                    """
                    INSERT INTO external_mirrors(
                        name, endpoint_url, auth_token_hash, enabled,
                        push_interval_seconds, data_scopes, retention_days,
                        last_push_watermark, consecutive_failures,
                        created_at, created_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
                    """,
                    (
                        name,
                        endpoint_url,
                        token_hash,
                        1 if enabled else 0,
                        int(push_interval_seconds),
                        scopes_json,
                        int(retention_days) if retention_days is not None else None,
                        now,
                        created_by,
                    ),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                raise MirrorNameConflictError(f"mirror name already exists: {name}") from exc

            mirror_id = int(cur.lastrowid)
            mirror = self._get_locked(mirror_id)

        # Audit (acquires lock again — fine because RLock).
        self.log_event(
            mirror_id,
            "created",
            actor=created_by,
            details={
                "endpoint_url": endpoint_url,
                "scopes": scopes_list,
                "push_interval_seconds": int(push_interval_seconds),
                "enabled": bool(enabled),
            },
        )
        return CreateMirrorResult(mirror=mirror, plaintext_token=token)

    def _get_locked(self, mirror_id: int) -> ExternalMirror:
        cur = self._conn.execute(
            "SELECT * FROM external_mirrors WHERE id = ?", (int(mirror_id),)
        )
        row = cur.fetchone()
        if row is None:
            raise MirrorNotFoundError(f"mirror id {mirror_id} not found")
        return _row_to_mirror(row)

    def get(self, mirror_id: int) -> Optional[ExternalMirror]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM external_mirrors WHERE id = ?", (int(mirror_id),)
            )
            row = cur.fetchone()
        return _row_to_mirror(row) if row else None

    def get_by_name(self, name: str) -> Optional[ExternalMirror]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM external_mirrors WHERE name = ?", (name,)
            )
            row = cur.fetchone()
        return _row_to_mirror(row) if row else None

    def list(self, *, include_disabled: bool = True) -> List[ExternalMirror]:
        with self._lock:
            if include_disabled:
                cur = self._conn.execute(
                    "SELECT * FROM external_mirrors ORDER BY name ASC"
                )
            else:
                cur = self._conn.execute(
                    "SELECT * FROM external_mirrors WHERE enabled = 1 ORDER BY name ASC"
                )
            rows = cur.fetchall()
        return [_row_to_mirror(r) for r in rows]

    _UPDATABLE_FIELDS = {
        "name",
        "endpoint_url",
        "push_interval_seconds",
        "data_scopes",
        "retention_days",
        "enabled",
    }

    def update(
        self,
        mirror_id: int,
        *,
        actor: Optional[str] = None,
        **fields: Any,
    ) -> ExternalMirror:
        unknown = set(fields).difference(self._UPDATABLE_FIELDS)
        if unknown:
            raise ValueError(f"unknown updatable fields: {sorted(unknown)}")
        if not fields:
            existing = self.get(mirror_id)
            if existing is None:
                raise MirrorNotFoundError(f"mirror id {mirror_id} not found")
            return existing

        with self._lock:
            current = self._get_locked(mirror_id)
            assignments: List[str] = []
            params: List[Any] = []
            diff: Dict[str, Dict[str, Any]] = {}

            for key, new_value in fields.items():
                if key == "data_scopes":
                    new_value = list(new_value) if new_value is not None else []
                    stored = json.dumps(new_value)
                    old_value = current.data_scopes
                    if old_value != new_value:
                        assignments.append("data_scopes = ?")
                        params.append(stored)
                        diff[key] = {"from": old_value, "to": new_value}
                elif key == "enabled":
                    new_value = bool(new_value)
                    old_value = current.enabled
                    if old_value != new_value:
                        assignments.append("enabled = ?")
                        params.append(1 if new_value else 0)
                        diff[key] = {"from": old_value, "to": new_value}
                elif key == "push_interval_seconds":
                    new_value = int(new_value)
                    if new_value < 10:
                        raise ValueError("push_interval_seconds must be >= 10")
                    old_value = current.push_interval_seconds
                    if old_value != new_value:
                        assignments.append("push_interval_seconds = ?")
                        params.append(new_value)
                        diff[key] = {"from": old_value, "to": new_value}
                elif key == "retention_days":
                    new_value = int(new_value) if new_value is not None else None
                    old_value = current.retention_days
                    if old_value != new_value:
                        assignments.append("retention_days = ?")
                        params.append(new_value)
                        diff[key] = {"from": old_value, "to": new_value}
                elif key == "name":
                    new_value = (new_value or "").strip()
                    if not new_value:
                        raise ValueError("name cannot be empty")
                    if new_value != current.name:
                        assignments.append("name = ?")
                        params.append(new_value)
                        diff[key] = {"from": current.name, "to": new_value}
                elif key == "endpoint_url":
                    new_value = (new_value or "").strip()
                    if not new_value:
                        raise ValueError("endpoint_url cannot be empty")
                    if new_value != current.endpoint_url:
                        assignments.append("endpoint_url = ?")
                        params.append(new_value)
                        diff[key] = {"from": current.endpoint_url, "to": new_value}

            if not assignments:
                return current

            assignments.append("updated_at = ?")
            params.append(_utcnow_iso())
            params.append(int(mirror_id))

            try:
                self._conn.execute(
                    f"UPDATE external_mirrors SET {', '.join(assignments)} WHERE id = ?",
                    params,
                )
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                raise MirrorNameConflictError(
                    f"mirror name conflict on update: {fields.get('name')}"
                ) from exc

            updated = self._get_locked(mirror_id)

        self.log_event(mirror_id, "updated", actor=actor, details={"diff": diff})
        return updated

    def delete(self, mirror_id: int, *, actor: Optional[str] = None) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM external_mirrors WHERE id = ?", (int(mirror_id),)
            )
            self._conn.commit()
            deleted = cur.rowcount > 0
        if deleted:
            # mirror_id no longer exists, so audit row will be deleted by FK CASCADE.
            # We still log to a best-effort extent; the FK CASCADE will remove this row,
            # which is acceptable (the deletion itself is the audit trail in upstream logs).
            try:
                self.log_event(mirror_id, "deleted", actor=actor)
            except sqlite3.IntegrityError:
                pass
        return deleted

    def set_enabled(
        self, mirror_id: int, enabled: bool, *, actor: Optional[str] = None
    ) -> ExternalMirror:
        with self._lock:
            current = self._get_locked(mirror_id)
            if current.enabled == bool(enabled):
                return current
            now = _utcnow_iso()
            # Re-enabling clears auto-disable bookkeeping.
            if enabled:
                self._conn.execute(
                    """
                    UPDATE external_mirrors
                    SET enabled = 1,
                        consecutive_failures = 0,
                        auto_disabled_at = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now, int(mirror_id)),
                )
            else:
                self._conn.execute(
                    "UPDATE external_mirrors SET enabled = 0, updated_at = ? WHERE id = ?",
                    (now, int(mirror_id)),
                )
            self._conn.commit()
            updated = self._get_locked(mirror_id)
        self.log_event(
            mirror_id,
            "enabled" if enabled else "disabled",
            actor=actor,
        )
        return updated

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------
    def rotate_token(
        self, mirror_id: int, *, actor: Optional[str] = None
    ) -> RotateTokenResult:
        new_token = generate_secure_token(DEFAULT_TOKEN_BYTES)
        new_hash = hash_password(new_token)
        now = _utcnow_iso()
        with self._lock:
            self._get_locked(mirror_id)  # raises if missing
            self._conn.execute(
                "UPDATE external_mirrors SET auth_token_hash = ?, updated_at = ? WHERE id = ?",
                (new_hash, now, int(mirror_id)),
            )
            self._conn.commit()
            updated = self._get_locked(mirror_id)
        self.log_event(mirror_id, "token_rotated", actor=actor)
        return RotateTokenResult(mirror=updated, plaintext_token=new_token)

    def verify_token(self, mirror_id: int, plaintext_token: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT auth_token_hash FROM external_mirrors WHERE id = ?",
                (int(mirror_id),),
            )
            row = cur.fetchone()
        if row is None:
            return False
        return verify_password(plaintext_token or "", row["auth_token_hash"])

    # ------------------------------------------------------------------
    # Push bookkeeping
    # ------------------------------------------------------------------
    def update_after_push(
        self,
        mirror_id: int,
        *,
        success: bool,
        watermark: Optional[int] = None,
        status_msg: Optional[str] = None,
    ) -> ExternalMirror:
        now = _utcnow_iso()
        auto_disabled = False
        with self._lock:
            current = self._get_locked(mirror_id)
            if success:
                new_watermark = (
                    int(watermark) if watermark is not None else current.last_push_watermark
                )
                self._conn.execute(
                    """
                    UPDATE external_mirrors
                    SET last_push_at = ?,
                        last_push_status = ?,
                        last_push_watermark = ?,
                        consecutive_failures = 0,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        now,
                        (status_msg or "ok")[:200],
                        new_watermark,
                        now,
                        int(mirror_id),
                    ),
                )
            else:
                new_failures = current.consecutive_failures + 1
                msg = f"error:{status_msg}" if status_msg else "error"
                if new_failures >= self._auto_disable_threshold:
                    auto_disabled = True
                    self._conn.execute(
                        """
                        UPDATE external_mirrors
                        SET last_push_at = ?,
                            last_push_status = ?,
                            consecutive_failures = ?,
                            enabled = 0,
                            auto_disabled_at = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (now, msg[:200], new_failures, now, now, int(mirror_id)),
                    )
                else:
                    self._conn.execute(
                        """
                        UPDATE external_mirrors
                        SET last_push_at = ?,
                            last_push_status = ?,
                            consecutive_failures = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (now, msg[:200], new_failures, now, int(mirror_id)),
                    )
            self._conn.commit()
            updated = self._get_locked(mirror_id)

        if auto_disabled:
            self.log_event(
                mirror_id,
                "auto_disabled",
                actor=None,
                details={
                    "consecutive_failures": updated.consecutive_failures,
                    "threshold": self._auto_disable_threshold,
                    "last_status": updated.last_push_status,
                },
            )
        return updated
