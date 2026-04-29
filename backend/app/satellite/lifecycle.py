# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
Satellite module — lifecycle management.

start_scheduler() / stop_scheduler() are called:
- at server startup if satellite_module_installed == "true" (main.py lifespan)
- immediately after install() succeeds (no restart required)
- immediately before uninstall() removes DB tables
"""

import asyncio
import logging

_log = logging.getLogger("uvicorn.error")

_scheduler_task: asyncio.Task | None = None


async def start_scheduler() -> None:
    """Start the satellite pass-prediction background loop (idempotent)."""
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _log.debug("Satellite scheduler already running — skipping start.")
        return
    _scheduler_task = asyncio.create_task(_scheduler_loop(), name="satellite_scheduler")
    _log.info("Satellite scheduler started.")


async def stop_scheduler() -> None:
    """Stop the satellite pass-prediction background loop (idempotent)."""
    global _scheduler_task
    if not _scheduler_task or _scheduler_task.done():
        return
    _scheduler_task.cancel()
    try:
        await _scheduler_task
    except asyncio.CancelledError:
        pass
    _scheduler_task = None
    _log.info("Satellite scheduler stopped.")


def is_running() -> bool:
    return bool(_scheduler_task and not _scheduler_task.done())


# ── Scheduler loop ────────────────────────────────────────────────────────────

_REFRESH_INTERVAL_S = 3600  # recalculate passes every hour


async def _scheduler_loop() -> None:
    """
    Hourly background task:
    - Recomputes upcoming passes for all enabled satellites.
    - Emits 'tle_status_changed' WebSocket events when TLE badge changes.
    - Prunes passes older than the retention window.
    """
    await asyncio.sleep(5)  # brief delay to let startup settle
    while True:
        try:
            await _run_cycle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.warning("Satellite scheduler cycle error: %s", exc)
        await asyncio.sleep(_REFRESH_INTERVAL_S)


async def _run_cycle() -> None:
    from app.dependencies import state as _state
    from app.satellite.propagator import compute_passes_for_all
    from app.satellite.tle_manager import get_tle_badge

    try:
        await compute_passes_for_all()
    except Exception as exc:
        _log.warning("Satellite pass computation error: %s", exc)

    # Emit TLE status badge to any open /ws/satellite clients
    try:
        badge = get_tle_badge(_state.db)
        from app.websocket.satellite import broadcast_tle_status
        await broadcast_tle_status(badge)
    except Exception as exc:
        _log.debug("Satellite TLE broadcast error: %s", exc)
