# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
Satellite API — /api/satellite/*

All endpoints check satellite_module_installed before doing anything
satellite-specific, returning 503 + {"detail": "not_installed"} if not.

Rate-limited install/import endpoints require admin auth.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.dependencies import state
from app.dependencies.auth import verify_basic_auth

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _require_installed():
    if not state.db.get_kv("satellite_module_installed") == "true":
        raise HTTPException(status_code=503, detail="not_installed")


# ── Install / Uninstall ────────────────────────────────────────────────────────

@router.get("/status")
async def satellite_status() -> dict[str, Any]:
    """Return module installed state + TLE badge.  Always available."""
    from app.satellite.installer import get_status
    return get_status(state.db)


@router.post("/install")
@limiter.limit("3/hour")
async def satellite_install(
    request: Request,
    _auth=Depends(verify_basic_auth),
) -> dict[str, str]:
    """Kick off async installation.  Returns job_id to poll."""
    from app.satellite.installer import install
    try:
        job_id = await install(state.db)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"job_id": job_id}


@router.get("/install/{job_id}")
async def satellite_install_status(job_id: str) -> dict[str, Any]:
    """Poll installation job progress."""
    from app.satellite.installer import get_job_status
    job = get_job_status(state.db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    return job


@router.post("/uninstall")
async def satellite_uninstall(
    request: Request,
    purge: bool = False,
    _auth=Depends(verify_basic_auth),
) -> dict[str, Any]:
    """Disable (or purge) the satellite module."""
    from app.satellite.installer import uninstall
    await uninstall(state.db, purge=purge)
    return {"ok": True, "purged": purge}


# ── Catalog ────────────────────────────────────────────────────────────────────

@router.get("/catalog")
async def get_catalog(enabled_only: bool = False) -> list[dict[str, Any]]:
    _require_installed()
    from app.satellite.catalog_manager import list_catalog
    return list_catalog(state.db, enabled_only=enabled_only)


@router.post("/catalog/refresh")
@limiter.limit("10/hour")
async def refresh_catalog(
    request: Request,
    _auth=Depends(verify_basic_auth),
) -> dict[str, Any]:
    _require_installed()
    from app.satellite.catalog_manager import refresh_catalog as _refresh
    return await _refresh(state.db)


@router.post("/catalog/import")
@limiter.limit("10/hour")
async def import_catalog(
    request: Request,
    _auth=Depends(verify_basic_auth),
) -> dict[str, Any]:
    """Upload a catalog JSON as raw request body (Content-Type: application/json or octet-stream)."""
    _require_installed()
    raw = await request.body()
    from app.satellite.catalog_manager import import_catalog_from_bytes
    result = await import_catalog_from_bytes(state.db, raw)
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.post("/catalog/{norad_id}/enable")
async def set_catalog_enabled(
    norad_id: int,
    enabled: bool = True,
    _auth=Depends(verify_basic_auth),
) -> dict[str, Any]:
    _require_installed()
    from app.satellite.catalog_manager import set_satellite_enabled
    ok = set_satellite_enabled(state.db, norad_id, enabled)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"ok": True, "norad_id": norad_id, "enabled": enabled}


@router.delete("/catalog/{norad_id}")
async def delete_catalog_entry(
    norad_id: int,
    _auth=Depends(verify_basic_auth),
) -> dict[str, Any]:
    _require_installed()
    from app.satellite.catalog_manager import delete_satellite
    ok = delete_satellite(state.db, norad_id)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"ok": True, "norad_id": norad_id}


# ── TLEs ──────────────────────────────────────────────────────────────────────

@router.get("/tles/status")
async def tle_status() -> dict[str, Any]:
    _require_installed()
    from app.satellite.tle_manager import get_tle_badge
    return get_tle_badge(state.db)


@router.post("/tles/refresh")
@limiter.limit("10/hour")
async def refresh_tles(
    request: Request,
    _auth=Depends(verify_basic_auth),
) -> dict[str, Any]:
    _require_installed()
    from app.satellite.tle_manager import refresh_tles as _refresh
    result = await _refresh(state.db)
    if result["ok"]:
        # Trigger pass recomputation in background
        from app.satellite.propagator import compute_passes_for_all
        import asyncio
        asyncio.create_task(compute_passes_for_all(state.db))
    return result


@router.post("/tles/import")
@limiter.limit("10/hour")
async def import_tles(
    request: Request,
    _auth=Depends(verify_basic_auth),
) -> dict[str, Any]:
    """Upload a TLE text file as raw request body (Content-Type: text/plain)."""
    _require_installed()
    raw = await request.body()
    from app.satellite.tle_manager import import_tles_from_bytes
    result = await import_tles_from_bytes(state.db, raw)
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


# ── Passes ─────────────────────────────────────────────────────────────────────

@router.get("/passes")
async def get_passes(hours: int = 24) -> list[dict[str, Any]]:
    _require_installed()
    if hours < 1 or hours > 168:
        raise HTTPException(status_code=422, detail="hours must be 1-168")
    from app.satellite.propagator import get_upcoming_passes
    return get_upcoming_passes(state.db, hours=hours)


@router.get("/passes/active")
async def get_active_pass() -> dict[str, Any] | None:
    _require_installed()
    from app.satellite.propagator import get_active_pass
    return get_active_pass(state.db)


@router.post("/passes/recompute")
@limiter.limit("5/hour")
async def recompute_passes(
    request: Request,
    _auth=Depends(verify_basic_auth),
) -> dict[str, Any]:
    _require_installed()
    import asyncio
    from app.satellite.propagator import compute_passes_for_all
    asyncio.create_task(compute_passes_for_all(state.db))
    return {"ok": True, "message": "Recomputation started in background"}


# ── Events ─────────────────────────────────────────────────────────────────────

@router.get("/events")
async def get_satellite_events(
    pass_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    _require_installed()
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=422, detail="limit must be 1-1000")
    sql = "SELECT * FROM satellite_events"
    params: list[Any] = []
    if pass_id is not None:
        sql += " WHERE pass_id = ?"
        params.append(pass_id)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    rows = state.db.conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


# ── Settings ───────────────────────────────────────────────────────────────────

@router.post("/settings")
async def save_satellite_settings(
    body: dict[str, Any],
    _auth=Depends(verify_basic_auth),
) -> dict[str, Any]:
    """
    Merge satellite settings into the user settings block.
    Body: {"station": {lat, lon, alt}, "min_elevation": float,
           "auto_tune": bool, "decoder_mode": str}
    """
    current = state.db.get_settings()
    current["satellite"] = body
    # Also update station if provided (shared with main settings)
    if "station" in body:
        current["station"] = body["station"]
    state.db.save_settings(current)
    return {"ok": True}
