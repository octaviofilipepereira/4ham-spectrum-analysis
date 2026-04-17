# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

"""
Preset Scheduler
================
Background task that switches between rotation presets based on
time-of-day schedules stored in the ``preset_schedules`` DB table.

Each schedule row maps a rotation preset to a UTC time window
(``start_hhmm``–``end_hhmm``).  Windows that cross midnight are
supported (e.g. 23:00–09:00).

The scheduler checks every 30 s which preset should be active.
When the active preset changes, it stops the current rotation and
starts the new one via the scan API helper ``_apply_preset``.

If no enabled schedule matches the current time, the rotation is
left unchanged (no interruption).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)

# How often the scheduler wakes up to check the clock (seconds).
_CHECK_INTERVAL_S = 30


def _hhmm_to_minutes(hhmm: str) -> int:
    """Convert 'HH:MM' to minutes since midnight (0–1439)."""
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _time_in_window(now_min: int, start_min: int, end_min: int) -> bool:
    """Return True if *now_min* falls inside [start, end) in circular clock.

    Handles windows that cross midnight (e.g. start=23:00, end=09:00).
    """
    if start_min <= end_min:
        # Same-day window: e.g. 09:00–23:00
        return start_min <= now_min < end_min
    else:
        # Cross-midnight: e.g. 23:00–09:00
        return now_min >= start_min or now_min < end_min


# Type alias for the async callback that loads + starts a preset.
ApplyPresetCb = Callable[[int], Coroutine[Any, Any, bool]]


class PresetScheduler:
    """Background scheduler that activates rotation presets by time-of-day."""

    def __init__(
        self,
        get_schedules: Callable[[], List[Dict]],
        apply_preset_cb: ApplyPresetCb,
        stop_rotation_cb: Callable[[], Coroutine[Any, Any, Any]],
        is_rotation_running: Callable[[], bool] = lambda: True,
    ) -> None:
        self._get_schedules = get_schedules
        self._apply_preset = apply_preset_cb
        self._stop_rotation = stop_rotation_cb
        self._is_rotation_running = is_rotation_running
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._active_preset_id: Optional[int] = None

    # ── Public interface ──────────────────────────────────────────

    @property
    def running(self) -> bool:
        return self._running

    @property
    def active_preset_id(self) -> Optional[int]:
        return self._active_preset_id

    async def start(self) -> bool:
        if self._running:
            return False
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("preset_scheduler_started")
        return True

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("preset_scheduler_stopped")

    def status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "active_preset_id": self._active_preset_id,
        }

    # ── Internal loop ─────────────────────────────────────────────

    async def _loop(self) -> None:
        try:
            while self._running:
                try:
                    await self._tick()
                except Exception:
                    logger.exception("preset_scheduler_tick_error")
                await asyncio.sleep(_CHECK_INTERVAL_S)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False

    async def _tick(self) -> None:
        """Determine which preset should be active *right now* and switch if needed."""
        schedules = self._get_schedules()
        now_utc = datetime.now(timezone.utc)
        now_min = now_utc.hour * 60 + now_utc.minute

        target_preset_id: Optional[int] = None

        for sched in schedules:
            if not sched.get("enabled"):
                continue
            try:
                s_min = _hhmm_to_minutes(sched["start_hhmm"])
                e_min = _hhmm_to_minutes(sched["end_hhmm"])
            except (ValueError, KeyError):
                continue
            if _time_in_window(now_min, s_min, e_min):
                target_preset_id = sched["preset_id"]
                break  # first matching window wins

        if target_preset_id == self._active_preset_id:
            if self._is_rotation_running():
                return  # no change needed
            # Rotation died — re-apply the same preset
            logger.info(
                "preset_scheduler: rotation not running, re-applying preset_id=%s",
                target_preset_id,
            )

        if target_preset_id is None:
            # Outside any window — leave rotation unchanged
            logger.info(
                "preset_scheduler: outside all windows, keeping preset_id=%s",
                self._active_preset_id,
            )
            return

        # Switch to new preset
        logger.info(
            "preset_scheduler_switch from=%s to=%s",
            self._active_preset_id, target_preset_id,
        )
        try:
            ok = await self._apply_preset(target_preset_id)
            if ok:
                self._active_preset_id = target_preset_id
                logger.info("preset_scheduler_applied preset_id=%d", target_preset_id)
            else:
                logger.warning(
                    "preset_scheduler_apply_failed preset_id=%d", target_preset_id,
                )
        except Exception:
            logger.exception(
                "preset_scheduler_apply_error preset_id=%d", target_preset_id,
            )
