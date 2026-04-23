# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
"""
Payload builder for external mirror pushes.

Reads the local SQLite store and produces a JSON-serialisable dict
consisting of:
  * meta: timestamp, app version, mirror name, watermark.
  * events: callsign + occupancy events with id > watermark, capped.

The receiver is read-only / append-mostly; it is responsible for
deduping by (source_id, table) if it wants to.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..storage.db import Database
from ..version import APP_VERSION
from .snapshots import build_snapshot_bundle


# Batched event push.  Default raised to 5000 because the snapshot
# bundle is now tiny (only version/scan/settings/ionospheric — analytics
# and map/contacts are queried on the receiver side from MySQL), so we
# can ship far more events per HTTP POST without exceeding the typical
# 8 MB shared-host post_max_size.  At 5000 evt/tick × 60 s tick this
# clears a 200 k backlog in well under an hour.
DEFAULT_BATCH_SIZE = 5000
MAX_BATCH_SIZE = 5000


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _fetch_events_since(
    db: Database,
    table: str,
    watermark: int,
    limit: int,
) -> List[Dict[str, Any]]:
    if table not in {"callsign_events", "occupancy_events"}:
        raise ValueError(f"unsupported table: {table}")
    with db._lock:
        cur = db.conn.execute(
            f"SELECT * FROM {table} WHERE id > ? ORDER BY id ASC LIMIT ?",
            (int(watermark), int(limit)),
        )
        rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]


def _max_id(events: Sequence[Dict[str, Any]]) -> int:
    if not events:
        return 0
    return max(int(e.get("id") or 0) for e in events)


def _table_max_id(db: Database, table: str) -> int:
    with db._lock:
        row = db.conn.execute(f"SELECT MAX(id) AS m FROM {table}").fetchone()
    if not row:
        return 0
    return int(row["m"] or 0)


def _table_frontier(
    events: Sequence[Dict[str, Any]],
    db_max_id: int,
    batch_size: int,
    scope_active: bool,
) -> int:
    """
    Highest id this table is "safe through" after this batch.

    - If scope is not active for this push: the table places no
      constraint on the watermark — return db_max_id (or 0 if empty),
      which acts as +∞ when combined with min().
    - If we got fewer rows than batch_size: we drained everything up to
      the current db MAX, so frontier = db_max_id.
    - Otherwise: only safe through the last id we fetched.
    """
    if not scope_active:
        return db_max_id
    if len(events) < batch_size:
        return db_max_id
    return _max_id(events)


def build_payload(
    db: Database,
    *,
    mirror_name: str,
    last_watermark: int,
    scopes: Iterable[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Dict[str, Any]:
    """
    Build the push payload for a mirror.

    Watermark semantics: a single integer used for *both* event tables
    (callsign + occupancy share the cursor).  Each table fetches rows
    with id > watermark up to batch_size.  The new watermark advances
    only as far as is safe for *both* tables — i.e.  ``min`` of each
    table's frontier — so that a fast-moving table (occupancy) cannot
    cause a slow-moving one (callsign) to be skipped over.
    """
    batch_size = max(1, min(int(batch_size), MAX_BATCH_SIZE))
    scopes_set = {s.strip().lower() for s in scopes if s and isinstance(s, str)}
    if not scopes_set:
        # Default scopes when none configured.
        scopes_set = {"callsign_events", "occupancy_events"}

    callsign_active = "callsign_events" in scopes_set
    occupancy_active = "occupancy_events" in scopes_set

    callsign_events: List[Dict[str, Any]] = []
    occupancy_events: List[Dict[str, Any]] = []
    if callsign_active:
        callsign_events = _fetch_events_since(
            db, "callsign_events", last_watermark, batch_size
        )
    if occupancy_active:
        occupancy_events = _fetch_events_since(
            db, "occupancy_events", last_watermark, batch_size
        )

    cs_db_max = _table_max_id(db, "callsign_events") if callsign_active else 0
    oc_db_max = _table_max_id(db, "occupancy_events") if occupancy_active else 0
    cs_frontier = _table_frontier(callsign_events, cs_db_max, batch_size, callsign_active)
    oc_frontier = _table_frontier(occupancy_events, oc_db_max, batch_size, occupancy_active)

    # Take the smaller of the two table frontiers so neither side is
    # skipped.  Disabled scopes return the other table's db_max so they
    # impose no constraint (min collapses to the active scope).
    if callsign_active and occupancy_active:
        candidate = min(cs_frontier, oc_frontier)
    elif callsign_active:
        candidate = cs_frontier
    elif occupancy_active:
        candidate = oc_frontier
    else:
        candidate = int(last_watermark)

    new_watermark = max(int(last_watermark), candidate)

    # Endpoint snapshot bundle: pre-computed JSON bodies for the live
    # endpoints the public dashboard needs (analytics, ionospheric, …).
    # The receiver UPSERTs each entry into mirror_endpoint_snapshots and
    # PHP shims serve them verbatim.  Wrapped defensively: a snapshot
    # failure must NEVER break event replication.
    try:
        snapshots = build_snapshot_bundle()
    except Exception:  # pragma: no cover - defensive
        snapshots = {}

    payload: Dict[str, Any] = {
        "meta": {
            "ts": _now_iso(),
            "app_version": APP_VERSION,
            "mirror_name": mirror_name,
            "previous_watermark": int(last_watermark),
            "new_watermark": new_watermark,
            "scopes": sorted(scopes_set),
            "batch_size": batch_size,
        },
        "events": {
            "callsign": callsign_events,
            "occupancy": occupancy_events,
        },
        "counts": {
            "callsign": len(callsign_events),
            "occupancy": len(occupancy_events),
        },
        "snapshots": snapshots,
    }
    return payload


def has_new_data(payload: Dict[str, Any]) -> bool:
    counts = payload.get("counts", {}) or {}
    return any(int(v or 0) > 0 for v in counts.values())


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "MAX_BATCH_SIZE",
    "build_payload",
    "has_new_data",
]
