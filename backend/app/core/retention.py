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

    1. Identifies purgeable events (age + count criteria).
    2. Exports them to CSV if RETENTION_AUTO_EXPORT=1.
    3. Deletes them from the database.
    4. Stores a notification in state for the next ws/status broadcast.

    Returns:
        Notification dict if any events were purged, None otherwise.
    """
    from app.dependencies import state as _state

    days = _state.retention_days
    max_events = _state.retention_max_events

    # Both limits disabled — nothing to do
    if days == 0 and max_events == 0:
        return None

    result = _state.db.get_purgeable_events(days=days, max_events=max_events)

    if not result["count"]:
        return None  # nothing to purge

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
    return notification
