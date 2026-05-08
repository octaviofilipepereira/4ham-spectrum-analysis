# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
Satellite module — pass propagator.

Uses pyorbital (lazy import) to compute upcoming passes for all enabled
satellites in satellite_catalog.  Results written to satellite_passes table.

All pyorbital imports are lazy so the server starts even when pyorbital is
not installed (satellite module not yet installed).
"""

import importlib
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

_log = logging.getLogger("uvicorn.error")

_PREDICT_HOURS = 24      # hours of horizon to predict
_MIN_ELEVATION = 5.0     # degrees


def _lazy_pyorbital():
    """Import pyorbital lazily; raises ImportError if not installed."""
    importlib.invalidate_caches()
    return importlib.import_module("pyorbital.orbital")


# ── Public API ────────────────────────────────────────────────────────────────

def compute_passes(
    db,
    norad_id: int,
    lat: float,
    lon: float,
    alt: float,
    hours: int = _PREDICT_HOURS,
) -> list[dict[str, Any]]:
    """
    Compute upcoming passes for a single satellite using its cached TLE.

    Returns list of pass dicts (aos, los, max_elevation, max_az, tle_epoch).
    Raises RuntimeError if pyorbital not available or TLE missing.
    """
    orbital = _lazy_pyorbital()

    sat = db.conn.execute(
        "SELECT name, tle_line1, tle_line2, tle_epoch, min_elevation_deg "
        "FROM satellite_catalog WHERE norad_id = ?",
        (norad_id,),
    ).fetchone()
    if not sat or not sat["tle_line1"] or not sat["tle_line2"]:
        raise RuntimeError(f"No TLE available for NORAD {norad_id}")

    min_elev = sat["min_elevation_deg"] or _MIN_ELEVATION
    orb = orbital.Orbital(
        sat["name"],
        line1=sat["tle_line1"],
        line2=sat["tle_line2"],
    )
    now_utc = datetime.now(timezone.utc)
    try:
        passes_raw = orb.get_next_passes(now_utc, hours, lon, lat, alt)
    except Exception as exc:
        raise RuntimeError(f"pyorbital error for NORAD {norad_id}: {exc}") from exc

    passes: list[dict[str, Any]] = []
    for entry in passes_raw:
        # pyorbital.Orbital.get_next_passes returns tuples of
        # (rise_time, fall_time, max_elevation_time) — all datetimes.
        # The actual peak elevation must be looked up separately.
        try:
            aos, los, max_t = entry
        except ValueError:
            continue
        try:
            az_max, el_max = orb.get_observer_look(max_t, lon, lat, alt)
        except Exception:
            # If we can't sample peak elevation, fall back to a permissive
            # value so the pass is not silently dropped.
            az_max, el_max = None, min_elev
        if el_max < min_elev:
            continue
        passes.append(
            {
                "norad_id": norad_id,
                "aos": _dt_iso(aos),
                "los": _dt_iso(los),
                "max_elevation": round(float(el_max), 2),
                "max_az": round(float(az_max), 2) if az_max is not None else None,
                "tle_epoch": sat["tle_epoch"],
            }
        )
    return passes


async def compute_passes_for_all(db=None) -> int:
    """Async wrapper: runs the CPU-heavy SGP4 propagation in a worker thread
    so the event loop stays responsive."""
    import asyncio
    return await asyncio.to_thread(_compute_passes_for_all_sync, db)


def _compute_passes_for_all_sync(db=None) -> int:
    """
    Recompute passes for all enabled satellites in the catalog.
    Saves results to satellite_passes table (replaces future passes, keeps past).
    Returns total number of passes written.

    This function is fully synchronous and CPU-heavy. Always invoke it via
    `compute_passes_for_all()` (which dispatches it to a thread executor),
    or directly from a worker thread — never from the asyncio event loop
    thread, or it will block FastAPI / WebSocket request handling.
    """
    if db is None:
        from app.dependencies import state as _state
        db = _state.db

    settings = db.get_settings()
    station = settings.get("station") or {}
    lat = float(station.get("lat") or 0.0)
    lon = float(station.get("lon") or 0.0)
    alt = float(station.get("alt") or 0.0)

    if lat == 0.0 and lon == 0.0:
        _log.debug("Satellite propagator: station lat/lon not configured, skipping.")
        return 0

    enabled = db.conn.execute(
        "SELECT norad_id FROM satellite_catalog WHERE enabled = 1 AND tle_line1 IS NOT NULL"
    ).fetchall()

    # Delete future predicted passes (keep completed/active)
    now_iso = datetime.now(timezone.utc).isoformat()
    with db._lock:
        db.conn.execute(
            "DELETE FROM satellite_passes WHERE aos > ? AND status = 'predicted'",
            (now_iso,),
        )
        db.conn.commit()

    total = 0
    for row in enabled:
        norad_id = row[0]
        try:
            passes = compute_passes(db, norad_id, lat, lon, alt)
            _save_passes(db, passes)
            total += len(passes)
        except Exception as exc:
            _log.warning("Pass compute error NORAD %d: %s", norad_id, exc)

    _log.info("Satellite propagator: %d passes computed for %d satellites.", total, len(enabled))
    return total


def get_upcoming_passes(db, hours: int = 24) -> list[dict[str, Any]]:
    """Return upcoming predicted passes sorted by AOS, within the next `hours` hours."""
    now_iso = datetime.now(timezone.utc).isoformat()
    horizon_iso = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    rows = db.conn.execute(
        """
        SELECT p.*, c.name AS satellite_name
        FROM satellite_passes p
        LEFT JOIN satellite_catalog c ON c.norad_id = p.norad_id
        WHERE p.aos >= ? AND p.aos <= ? AND p.status = 'predicted'
        ORDER BY p.aos
        """,
        (now_iso, horizon_iso),
    ).fetchall()
    return [dict(r) for r in rows]


def get_active_pass(db) -> dict[str, Any] | None:
    """Return the currently active pass (AOS <= now <= LOS), if any."""
    now_iso = datetime.now(timezone.utc).isoformat()
    row = db.conn.execute(
        """
        SELECT p.*, c.name AS satellite_name
        FROM satellite_passes p
        LEFT JOIN satellite_catalog c ON c.norad_id = p.norad_id
        WHERE p.aos <= ? AND p.los >= ?
        ORDER BY p.aos DESC
        LIMIT 1
        """,
        (now_iso, now_iso),
    ).fetchone()
    return dict(row) if row else None


# ── Internals ─────────────────────────────────────────────────────────────────

def _save_passes(db, passes: list[dict[str, Any]]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with db._lock:
        for p in passes:
            db.conn.execute(
                """
                INSERT INTO satellite_passes
                    (norad_id, aos, los, max_elevation, max_az, status, tle_epoch, created_at)
                VALUES (?, ?, ?, ?, ?, 'predicted', ?, ?)
                """,
                (
                    p["norad_id"], p["aos"], p["los"],
                    p["max_elevation"], p["max_az"],
                    p["tle_epoch"], now,
                ),
            )
        db.conn.commit()


def _dt_iso(dt: Any) -> str:
    """Convert a datetime (possibly naive UTC from pyorbital) to ISO string."""
    if hasattr(dt, "tzinfo") and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
