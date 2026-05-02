# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
WebSocket /ws/beacons

Streams two event types:
  slot_start     — emitted at the start of each 10-second NCDXF slot
                   { type, callsign, freq_hz, slot_index, slot_start_utc,
                     band_name, beacon_index, beacon_location }
  observation    — emitted after SlotDetector finishes (end of slot)
                   { type, ...full observation dict }

The scheduler calls broadcast_slot_start() / broadcast_observation()
which are wired up in main.py via on_slot_start / on_observation callbacks.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.dependencies import state
from app.beacons.catalog import BEACONS, BANDS, beacon_at

router = APIRouter()
_log = logging.getLogger("uvicorn.error")

# Registry of active connections
_connections: set[WebSocket] = set()


@router.websocket("/ws/beacons")
async def ws_beacons(websocket: WebSocket) -> None:
    # Auth check — same pattern as ws_satellite
    if state.auth_required and not state.verify_auth_transport(
        websocket.headers.get("authorization"),
        websocket.headers.get("cookie"),
    ):
        await websocket.close(code=1008)
        return

    await websocket.accept()
    _connections.add(websocket)

    try:
        # Send initial status snapshot on connect
        sched = getattr(state, "beacon_scheduler", None)
        snapshot = sched.snapshot() if sched else {"running": False}
        await websocket.send_text(json.dumps({
            "type": "beacon_status",
            "scheduler": snapshot,
            "catalog": {
                "beacons": [b.callsign for b in BEACONS],
                "bands": [b.name for b in BANDS],
            },
        }))

        # Keep-alive loop — all real data comes via broadcasts
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        _log.debug("ws_beacons error: %s", exc)
    finally:
        _connections.discard(websocket)


async def broadcast_slot_start(
    callsign: str,
    freq_hz: int,
    slot_index: int,
    slot_start_utc: str,
) -> None:
    """Called by BeaconScheduler.on_slot_start — broadcast slot_start event."""
    if not _connections:
        return
    band = next((b for b in BANDS if b.freq_hz == freq_hz), None)
    band_index = band.index if band else 0
    # Per the NCDXF schedule, the beacon transmitting at slot S on band B is
    # BEACONS[(S - B) % 18]. The frontend matrix needs the row to be the
    # beacon index, not the raw slot index, so it stays aligned across bands.
    beacon = beacon_at(slot_index % 18, band_index)
    msg = json.dumps({
        "type": "slot_start",
        "callsign": callsign,
        "freq_hz": freq_hz,
        "slot_index": slot_index,
        "slot_start_utc": slot_start_utc,
        "band_name": band.name if band else None,
        "beacon_index": beacon.index,
    })
    await _broadcast(msg)


async def broadcast_observation(obs: dict[str, Any]) -> None:
    """Called by BeaconScheduler.on_observation — broadcast observation event."""
    if not _connections:
        return
    msg = json.dumps({"type": "observation", **obs})
    await _broadcast(msg)


async def _broadcast(msg: str) -> None:
    dead: set[WebSocket] = set()
    for ws in list(_connections):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _connections.difference_update(dead)
