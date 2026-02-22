# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 17:40:00 UTC

import asyncio
from datetime import datetime, timezone


class InternalFtDecoder:
    def __init__(
        self,
        modes=None,
        compare_with_wsjtx=False,
        min_confidence=0.0,
        poll_s=1.0,
        logger=None,
    ):
        self.modes = list(modes or ["FT8", "FT4"])
        self.compare_with_wsjtx = bool(compare_with_wsjtx)
        self.min_confidence = float(min_confidence)
        self.poll_s = max(0.1, float(poll_s))
        self.logger = logger

        self._task = None
        self._running = False
        self._started_at = None
        self._stopped_at = None
        self._last_heartbeat_at = None
        self._last_error = None

    def _log(self, message):
        if not self.logger:
            return
        try:
            self.logger(message)
        except Exception:
            return

    async def start(self):
        if self._running and self._task and not self._task.done():
            return False

        self._running = True
        self._last_error = None
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._stopped_at = None
        self._last_heartbeat_at = self._started_at
        self._task = asyncio.create_task(self._run())
        self._log("ft_internal_started")
        return True

    async def stop(self):
        self._running = False
        task = self._task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._stopped_at = datetime.now(timezone.utc).isoformat()
        self._log("ft_internal_stopped")
        return True

    async def _run(self):
        try:
            while self._running:
                self._last_heartbeat_at = datetime.now(timezone.utc).isoformat()
                await asyncio.sleep(self.poll_s)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._last_error = str(exc)
            self._log(f"ft_internal_failed {exc}")
            self._running = False

    def snapshot(self):
        running = bool(self._running and self._task and not self._task.done())
        return {
            "enabled": running,
            "running": running,
            "modes": list(self.modes),
            "compare_with_wsjtx": self.compare_with_wsjtx,
            "min_confidence": self.min_confidence,
            "poll_s": self.poll_s,
            "started_at": self._started_at,
            "stopped_at": self._stopped_at,
            "last_heartbeat_at": self._last_heartbeat_at,
            "last_error": self._last_error,
        }
