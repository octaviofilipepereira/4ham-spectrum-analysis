# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
Internet connectivity service.

Polls a lightweight TCP probe on a fixed interval and exposes the latest
result via :func:`get_status`.  The result is also folded into the
``/ws/status`` payload (see ``app/websocket/status.py``) so any frontend
already subscribed gets online/offline transitions for free.

Other backend code (e.g. SatNOGS metadata refresh, AMSAT status,
external mirrors) can call :func:`is_online` to decide whether to attempt
a network round-trip without performing its own probe.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from typing import Optional

_log = logging.getLogger("uvicorn.error")

# Polling cadence — slow enough not to spam the network, fast enough that
# an outage is reflected in the UI within a minute.
_POLL_INTERVAL_S = 60.0
# Probe timeout — short, so a flaky network does not stall the loop.
_PROBE_TIMEOUT_S = 3.0
# Public anycast resolvers — TCP/53 reachable in virtually every network
# that has real internet egress.  Listed in fallback order.
_PROBE_TARGETS = (
    ("1.1.1.1", 53),
    ("8.8.8.8", 53),
    ("9.9.9.9", 53),
)

_state = {
    "online": None,            # Optional[bool] — None until first probe
    "last_check_ts": None,     # epoch seconds of last probe
    "last_change_ts": None,    # epoch seconds of last online↔offline flip
    "consecutive_failures": 0,
}


def _probe_once(timeout: float = _PROBE_TIMEOUT_S) -> bool:
    """Synchronous TCP probe.  Tries each target until one succeeds."""
    for host, port in _PROBE_TARGETS:
        try:
            s = socket.create_connection((host, port), timeout=timeout)
            s.close()
            return True
        except OSError:
            continue
    return False


def get_status() -> dict:
    """Return current connectivity snapshot — safe to call from anywhere."""
    return {
        "online": _state["online"],
        "last_check_ts": _state["last_check_ts"],
        "last_change_ts": _state["last_change_ts"],
        "consecutive_failures": _state["consecutive_failures"],
    }


def is_online() -> bool:
    """Quick non-blocking accessor.  Returns False until first probe runs."""
    return bool(_state["online"])


async def probe_now(timeout: float = _PROBE_TIMEOUT_S) -> bool:
    """Force an immediate probe (off the loop) and update state."""
    online = await asyncio.to_thread(_probe_once, timeout)
    _update(online)
    return online


def _update(online: bool) -> None:
    now = time.time()
    prev = _state["online"]
    _state["last_check_ts"] = now
    if online:
        _state["consecutive_failures"] = 0
    else:
        _state["consecutive_failures"] += 1
    if prev is None or prev != online:
        _state["online"] = online
        _state["last_change_ts"] = now
        if prev is not None:
            _log.info(
                "Connectivity changed: %s → %s",
                "online" if prev else "offline",
                "online" if online else "offline",
            )


async def connectivity_loop() -> None:
    """Background poller — register from FastAPI lifespan."""
    # First probe right away so the UI does not sit on "unknown".
    try:
        await probe_now()
    except Exception as exc:  # pragma: no cover — defensive
        _log.warning("Initial connectivity probe failed: %s", exc)
    while True:
        try:
            await asyncio.sleep(_POLL_INTERVAL_S)
            await probe_now()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover — defensive
            _log.warning("Connectivity probe error: %s", exc)
            await asyncio.sleep(_POLL_INTERVAL_S)
