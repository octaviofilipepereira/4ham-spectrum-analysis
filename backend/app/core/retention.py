# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-23 21:30 UTC

"""
Event Retention
===============
Hybrid retention strategy: export events to CSV then purge them
based on age (RETENTION_DAYS) and/or count (MAX_EVENTS) limits.

Designed to be called:
  - Automatically at startup and every 24 h (via main.py lifespan)
  - Manually via POST /api/admin/retention/run
"""

import logging
from typing import Optional

_log = logging.getLogger("uvicorn.error")


async def run_retention() -> Optional[dict]:
    """
    Execute one retention cycle.

    Age-based purge (RETENTION_DAYS):
      Exports and deletes events older than N days.

    Count-based purge (MAX_EVENTS / RETENTION_KEEP_EVENTS):
      When total events >= MAX_EVENTS, exports ALL events to CSV and
      deletes everything except the RETENTION_KEEP_EVENTS most recent.

    Returns:
        Notification dict if any events were purged, None otherwise.
    """
    from app.dependencies import state as _state

    days = _state.retention_days
    max_events = _state.retention_max_events
    keep_events = _state.retention_keep_events

    # Both limits disabled — nothing to do
    if days == 0 and max_events == 0:
        return None

    # --- Count-based: check if threshold reached ---
    count_result = None
    if max_events > 0:
        total_occ = _state.db.conn.execute("SELECT COUNT(*) FROM occupancy_events").fetchone()[0]
        total_call = _state.db.conn.execute("SELECT COUNT(*) FROM callsign_events").fetchone()[0]
        total = total_occ + total_call
        if total >= max_events:
            _log.info("Retention: count threshold reached (%d >= %d), exporting all and keeping %d", total, max_events, keep_events)
            count_result = _state.db.get_all_events_and_keep_newest(keep=keep_events)

    # --- Age-based: standard partial purge ---
    age_result = None
    if days > 0:
        age_result = _state.db.get_purgeable_events(days=days, max_events=0)
        if not age_result["count"]:
            age_result = None

    # Nothing to do
    if count_result is None and age_result is None:
        return None

    # If count-based triggered, it takes priority and covers everything
    result = count_result if count_result is not None else age_result

    # --- Auto-export before deletion ---
    export_meta = None
    if _state.retention_auto_export and result["events"]:
        try:
            export_meta = _state.export_manager.create_export(
                result["events"], format_name="csv"
            )
            _log.info(
                "Retention: exported %d events → %s",
                export_meta["row_count"],
                export_meta["id"],
            )
        except Exception as exc:
            _log.warning("Retention export failed: %s", exc)

    # --- Delete ---
    deleted = _state.db.delete_events_by_ids(result["occ_ids"], result["call_ids"])

    _log.info(
        "Retention: purged %d events%s",
        deleted,
        f", export={export_meta['id']}" if export_meta else " (no export)",
    )

    # --- Build notification for ws/status broadcast ---
    notification = {
        "purged": deleted,
        "exported": bool(export_meta),
        "export_id": export_meta["id"] if export_meta else None,
        "export_rows": export_meta["row_count"] if export_meta else 0,
        "download_url": (
            f"/api/exports/{export_meta['id']}" if export_meta else None
        ),
    }

    _state.retention_notification = notification

    # Satellite module retention (no-op if module not installed)
    try:
        await run_satellite_retention()
    except Exception as exc:
        _log.debug("Satellite retention error: %s", exc)

    return notification


# ── Satellite retention ────────────────────────────────────────────────────────

async def run_satellite_retention() -> None:
    """Purge old satellite_passes (>30 days) and satellite_events (>90 days)."""
    from app.dependencies import state as _state
    from datetime import datetime, timezone, timedelta

    # Only run if satellite tables exist
    tables = {r[0] for r in _state.db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    if "satellite_passes" not in tables:
        return

    now = datetime.now(timezone.utc)
    cutoff_passes = (now - timedelta(days=30)).isoformat()
    cutoff_events = (now - timedelta(days=90)).isoformat()

    with _state.db._lock:
        p_del = _state.db.conn.execute(
            "DELETE FROM satellite_passes WHERE los < ?", (cutoff_passes,)
        ).rowcount
        e_del = _state.db.conn.execute(
            "DELETE FROM satellite_events WHERE timestamp < ?", (cutoff_events,)
        ).rowcount
        _state.db.conn.commit()

    if p_del or e_del:
        _log.info(
            "Satellite retention: %d passes (>30d) + %d events (>90d) purged.",
            p_del, e_del,
        )
