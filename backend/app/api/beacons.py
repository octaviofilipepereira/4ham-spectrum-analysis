# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
Beacon Analysis API — /api/beacons/*

Endpoints
---------
GET  /api/beacons/status          → scheduler snapshot + catalog summary
POST /api/beacons/start           → start scheduler (optional band selection)
POST /api/beacons/stop            → stop scheduler
GET  /api/beacons/catalog         → all 18 beacons with current status
GET  /api/beacons/matrix          → 18×5 matrix of current-cycle observations
GET  /api/beacons/observations    → paginated observation history (SQLite)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.dependencies import state
from app.beacons.catalog import BANDS, BEACONS, beacon_at, current_slot_index

router = APIRouter()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _scheduler():
    return getattr(state, "beacon_scheduler", None)


def _require_running():
    sched = _scheduler()
    if sched is None or not sched._running:
        raise HTTPException(status_code=409, detail="beacon_scheduler_not_running")


# ── Status ─────────────────────────────────────────────────────────────────────

@router.get("/status")
async def beacon_status() -> dict[str, Any]:
    """Return scheduler snapshot and a brief catalog summary."""
    sched = _scheduler()
    snapshot = sched.snapshot() if sched else {"running": False}
    return {
        "scheduler": snapshot,
        "catalog": {
            "beacons": len(BEACONS),
            "bands": len(BANDS),
            "active_beacons": sum(1 for b in BEACONS if b.status == "active"),
        },
    }


# ── Start / Stop ───────────────────────────────────────────────────────────────

@router.post("/start")
async def beacon_start(
    bands: list[str] | None = Query(default=None),
) -> dict[str, Any]:
    """Start the NCDXF beacon scheduler.

    Query param ``bands`` is an optional list of band names to monitor
    (e.g. ``?bands=20m&bands=15m``).  Defaults to all 5 bands.
    """
    sched = _scheduler()
    if sched is None:
        raise HTTPException(status_code=503, detail="beacon_scheduler_unavailable")

    if sched._running:
        return {"ok": False, "detail": "already_running", **sched.snapshot()}

    # Optionally restrict to a subset of bands
    if bands:
        band_map = {b.name: b for b in BANDS}
        selected = [band_map[n] for n in bands if n in band_map]
        if not selected:
            raise HTTPException(status_code=400, detail="no_valid_bands")
        sched._bands = selected
        sched._band_index = 0
        sched._slots_on_band = 0

    started = await sched.start()
    return {"ok": started, **sched.snapshot()}


@router.post("/stop")
async def beacon_stop() -> dict[str, Any]:
    """Stop the NCDXF beacon scheduler."""
    sched = _scheduler()
    if sched is None:
        raise HTTPException(status_code=503, detail="beacon_scheduler_unavailable")
    stopped = await sched.stop()
    return {"ok": stopped, **sched.snapshot()}


# ── Catalog ────────────────────────────────────────────────────────────────────

@router.get("/catalog")
async def beacon_catalog() -> list[dict[str, Any]]:
    """Return the full NCDXF beacon catalog."""
    return [
        {
            "index": b.index,
            "callsign": b.callsign,
            "location": b.location,
            "qth_locator": b.qth_locator,
            "lat": b.lat,
            "lon": b.lon,
            "status": b.status,
            "notes": b.notes,
        }
        for b in BEACONS
    ]


# ── Matrix ────────────────────────────────────────────────────────────────────

@router.get("/matrix")
async def beacon_matrix() -> dict[str, Any]:
    """Return the 18×5 observation matrix for the current UTC cycle.

    ``matrix[slot_index][band_index]`` contains the most recent observation
    for that cell (or null if none recorded yet this cycle).

    Also returns the current slot index for the frontend highlight.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    slot_idx = current_slot_index(now)

    # Pull last 18*5=90 observations from DB (one per slot×band cell max)
    rows = state.db.get_beacon_observations(limit=90)

    # Build lookup: (slot_index, band_name) → most recent observation
    cell: dict[tuple[int, str], dict] = {}
    for row in rows:
        key = (row["slot_index"] % 18, row["band_name"])
        if key not in cell:
            cell[key] = row

    # Build 18×5 matrix
    matrix: list[list[dict | None]] = []
    for s in range(18):
        row_data = []
        for band in BANDS:
            row_data.append(cell.get((s, band.name)))
        matrix.append(row_data)

    return {
        "current_slot_index": slot_idx,
        "bands": [b.name for b in BANDS],
        "beacons": [b.callsign for b in BEACONS],
        "matrix": matrix,
    }


# ── Observations ──────────────────────────────────────────────────────────────

@router.get("/observations")
async def beacon_observations(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    band: str | None = Query(default=None),
    callsign: str | None = Query(default=None),
    detected_only: bool = Query(default=False),
) -> dict[str, Any]:
    """Paginated beacon observation history."""
    rows = state.db.get_beacon_observations(
        limit=limit,
        offset=offset,
        band=band,
        callsign=callsign,
        detected_only=detected_only,
    )
    return {"observations": rows, "count": len(rows), "offset": offset}
