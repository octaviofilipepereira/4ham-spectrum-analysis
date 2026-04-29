# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
WebSocket /ws/satellite

Streams:
  - tle_status_changed  — emitted on scheduler cycle or manual refresh
  - pass_upcoming       — emitted pre-AOS for each satellite (future: Fase 2)
  - pass_end            — emitted at LOS (future: Fase 2)

Auth: same Basic Auth header pattern as ws_status.py / ws_events.py.
"""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.dependencies import state

router = APIRouter()
_log = logging.getLogger("uvicorn.error")

# Registry of active connections for broadcast
_connections: set[WebSocket] = set()


@router.websocket("/ws/satellite")
async def ws_satellite(websocket: WebSocket) -> None:
    # ── Auth check ────────────────────────────────────────────────
    if state.auth_enabled:
        auth_header = websocket.headers.get("authorization", "")
        from app.core.auth import parse_basic_auth
        from app.dependencies.auth import _verify_credentials
        creds = parse_basic_auth(auth_header)
        if not creds or not _verify_credentials(creds[0], creds[1]):
            await websocket.close(code=1008)
            return

    await websocket.accept()
    _connections.add(websocket)
    try:
        # Send initial TLE status on connect
        from app.satellite.tle_manager import get_tle_badge
        badge = get_tle_badge(state.db)
        await websocket.send_text(json.dumps({"type": "tle_status_changed", **badge}))

        # Keep alive — client pings are ignored; server broadcasts drive this WS
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                pass  # normal — no client messages expected
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        _log.debug("ws_satellite error: %s", exc)
    finally:
        _connections.discard(websocket)


async def broadcast_tle_status(badge: dict[str, Any]) -> None:
    """Broadcast tle_status_changed to all connected /ws/satellite clients."""
    if not _connections:
        return
    msg = json.dumps({"type": "tle_status_changed", **badge})
    dead: set[WebSocket] = set()
    for ws in list(_connections):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _connections.difference_update(dead)


async def broadcast_pass_upcoming(pass_data: dict[str, Any]) -> None:
    """Broadcast pass_upcoming event (called from Fase 2 scheduler)."""
    if not _connections:
        return
    msg = json.dumps({"type": "pass_upcoming", **pass_data})
    dead: set[WebSocket] = set()
    for ws in list(_connections):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _connections.difference_update(dead)
