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
        emit_mock_events=False,
        mock_interval_s=15.0,
        mock_callsign="N0CALL",
        on_event=None,
        frequency_provider=None,
        logger=None,
    ):
        self.modes = list(modes or ["FT8", "FT4"])
        self.compare_with_wsjtx = bool(compare_with_wsjtx)
        self.min_confidence = float(min_confidence)
        self.poll_s = max(0.1, float(poll_s))
        self.emit_mock_events = bool(emit_mock_events)
        self.mock_interval_s = max(self.poll_s, float(mock_interval_s))
        self.mock_callsign = str(mock_callsign or "N0CALL").strip().upper() or "N0CALL"
        self.on_event = on_event
        self.frequency_provider = frequency_provider
        self.logger = logger

        self._task = None
        self._running = False
        self._started_at = None
        self._stopped_at = None
        self._last_heartbeat_at = None
        self._last_event_at = None
        self._events_emitted = 0
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
        next_emit = 0.0
        try:
            while self._running:
                now = datetime.now(timezone.utc)
                self._last_heartbeat_at = now.isoformat()
                now_ts = now.timestamp()

                if self.emit_mock_events and self.on_event and now_ts >= next_emit:
                    next_emit = now_ts + self.mock_interval_s
                    payload = self._build_mock_event_payload(now)
                    try:
                        result = self.on_event(payload)
                        if asyncio.iscoroutine(result):
                            await result
                        self._last_event_at = now.isoformat()
                        self._events_emitted += 1
                    except Exception as exc:
                        self._last_error = str(exc)
                        self._log(f"ft_internal_event_failed {exc}")
                await asyncio.sleep(self.poll_s)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._last_error = str(exc)
            self._log(f"ft_internal_failed {exc}")
            self._running = False

    def _resolve_frequency_hz(self):
        if not self.frequency_provider:
            return None
        try:
            value = self.frequency_provider()
            if value is None:
                return None
            return int(value)
        except Exception:
            return None

    def _build_mock_event_payload(self, now):
        mode = self.modes[self._events_emitted % max(1, len(self.modes))] if self.modes else "FT8"
        payload = {
            "timestamp": now.isoformat(),
            "mode": str(mode).upper(),
            "callsign": self.mock_callsign,
            "snr_db": -12.0,
            "confidence": max(self.min_confidence, 0.75),
            "source": "internal_ft",
            "raw": "ft_internal_mock_event",
        }
        frequency_hz = self._resolve_frequency_hz()
        if frequency_hz and frequency_hz > 0:
            payload["frequency_hz"] = int(frequency_hz)
        return payload

    def snapshot(self):
        running = bool(self._running and self._task and not self._task.done())
        return {
            "enabled": running,
            "running": running,
            "modes": list(self.modes),
            "compare_with_wsjtx": self.compare_with_wsjtx,
            "min_confidence": self.min_confidence,
            "poll_s": self.poll_s,
            "emit_mock_events": self.emit_mock_events,
            "mock_interval_s": self.mock_interval_s,
            "mock_callsign": self.mock_callsign,
            "started_at": self._started_at,
            "stopped_at": self._stopped_at,
            "last_heartbeat_at": self._last_heartbeat_at,
            "last_event_at": self._last_event_at,
            "events_emitted": int(self._events_emitted),
            "last_error": self._last_error,
        }
