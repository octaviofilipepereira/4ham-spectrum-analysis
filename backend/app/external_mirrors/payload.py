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


DEFAULT_BATCH_SIZE = 500
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

    The shared watermark is a single integer applied across both event
    tables: each table fetches rows with id > watermark, and the new
    watermark returned is max(id) seen in this batch (or unchanged if
    nothing new).
    """
    batch_size = max(1, min(int(batch_size), MAX_BATCH_SIZE))
    scopes_set = {s.strip().lower() for s in scopes if s and isinstance(s, str)}
    if not scopes_set:
        # Default scopes when none configured.
        scopes_set = {"callsign_events", "occupancy_events"}

    callsign_events: List[Dict[str, Any]] = []
    occupancy_events: List[Dict[str, Any]] = []
    if "callsign_events" in scopes_set:
        callsign_events = _fetch_events_since(
            db, "callsign_events", last_watermark, batch_size
        )
    if "occupancy_events" in scopes_set:
        occupancy_events = _fetch_events_since(
            db, "occupancy_events", last_watermark, batch_size
        )

    new_watermark = max(
        int(last_watermark),
        _max_id(callsign_events),
        _max_id(occupancy_events),
    )

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
