# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
Satellite module — SatNOGS catalog manager.

Responsibilities:
- Fetch and merge the SatNOGS DB amateur/educational satellite catalog.
- Import a catalog from a manually uploaded JSON file (via validators.parse_catalog_json).
- Provide CRUD helpers for the satellite_catalog table.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger("uvicorn.error")

_SATNOGS_URL = "https://db.satnogs.org/api/satellites/?format=json&status=alive"
_CAT_SNAPSHOT = (
    Path(__file__).resolve().parents[3] / "data" / "satellite" / "catalog.json"
)
_ALLOWED_SERVICES = {"amateur", "educational"}


# ── Public API ────────────────────────────────────────────────────────────────

async def refresh_catalog(db) -> dict[str, Any]:
    """
    Fetch the SatNOGS DB catalog and merge into satellite_catalog.
    Returns {"ok": bool, "total": int, "merged": int, "error": str|None}.
    """
    import httpx
    from app.satellite.validators import ValidationError
    from app.core import connectivity

    # Skip the (potentially 60 s) network call when the connectivity probe
    # has confirmed we are offline.  Probe state is None on cold start —
    # only skip when an explicit offline result is known.
    if connectivity.get_status().get("online") is False:
        msg = "offline (connectivity probe): keeping cached catalog"
        _log.info("Catalog refresh skipped — %s", msg)
        db.set_kv("satellite_catalog_last_refresh_error", _now_iso())
        return {"ok": False, "total": 0, "merged": 0, "error": msg}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(_SATNOGS_URL)
            resp.raise_for_status()
            raw = resp.content
    except Exception as exc:
        err = str(exc)
        _log.warning("SatNOGS catalog fetch failed: %s", err)
        db.set_kv("satellite_catalog_last_refresh_error", _now_iso())
        return {"ok": False, "total": 0, "merged": 0, "error": err}

    try:
        from app.satellite.validators import parse_catalog_json
        entries = parse_catalog_json(raw)
    except Exception as exc:
        db.set_kv("satellite_catalog_last_refresh_error", _now_iso())
        return {"ok": False, "total": 0, "merged": 0, "error": f"Parse error: {exc}"}

    filtered = [
        e for e in entries
        if (e.get("service") or "").lower() in _ALLOWED_SERVICES
    ]
    merged = _upsert_catalog(db, filtered, source="satnogs")
    db.set_kv("satellite_catalog_last_refresh_ok", _now_iso())
    _log.info("Catalog refresh OK: %d/%d entries (amateur/educational).", merged, len(entries))
    return {"ok": True, "total": len(entries), "merged": merged, "error": None}


async def import_catalog_from_bytes(db, raw: bytes) -> dict[str, Any]:
    """
    Import catalog from manually uploaded JSON bytes.
    Returns {"ok": bool, "imported": int, "ignored": int, "error": str|None}.
    """
    from app.satellite.validators import parse_catalog_json, ValidationError

    try:
        entries = parse_catalog_json(raw)
    except ValidationError as exc:
        return {"ok": False, "imported": 0, "ignored": 0, "error": str(exc)}

    imported = _upsert_catalog(db, entries, source="manual")
    return {"ok": True, "imported": imported, "ignored": len(entries) - imported, "error": None}


def load_snapshot_catalog(db) -> int:
    """
    Load the bundled offline catalog snapshot into the DB (installer fallback).
    Returns number of entries loaded.
    """
    import json
    from app.satellite.validators import parse_catalog_json, ValidationError

    if not _CAT_SNAPSHOT.exists():
        _log.warning("Catalog snapshot not found: %s", _CAT_SNAPSHOT)
        return 0
    try:
        raw = _CAT_SNAPSHOT.read_bytes()
        entries = parse_catalog_json(raw)
    except (ValidationError, OSError) as exc:
        _log.warning("Catalog snapshot load error: %s", exc)
        return 0

    count = _upsert_catalog(db, entries, source="snapshot")
    _log.info("Catalog snapshot loaded: %d entries.", count)
    return count


def list_catalog(db, enabled_only: bool = False) -> list[dict[str, Any]]:
    """Return list of satellite_catalog rows as dicts."""
    sql = "SELECT * FROM satellite_catalog"
    if enabled_only:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY name"
    with db._lock:
        rows = db.conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def get_satellite(db, norad_id: int) -> dict[str, Any] | None:
    with db._lock:
        row = db.conn.execute(
            "SELECT * FROM satellite_catalog WHERE norad_id = ?", (norad_id,)
        ).fetchone()
    return dict(row) if row else None


def add_satellite(db, norad_id: int, name: str, **kwargs) -> dict[str, Any]:
    """Add or update a single satellite entry."""
    now = _now_iso()
    entry = {
        "norad_id": norad_id,
        "name": name,
        "downlink_hz": kwargs.get("downlink_hz"),
        "uplink_hz": kwargs.get("uplink_hz"),
        "mode": kwargs.get("mode"),
        "min_elevation_deg": kwargs.get("min_elevation_deg", 5.0),
        "enabled": 1,
        "source": kwargs.get("source", "manual"),
        "updated_at": now,
    }
    _upsert_catalog(db, [entry], source=entry["source"])
    return get_satellite(db, norad_id) or entry


def delete_satellite(db, norad_id: int) -> bool:
    with db._lock:
        cur = db.conn.execute(
            "DELETE FROM satellite_catalog WHERE norad_id = ?", (norad_id,)
        )
        db.conn.commit()
    return cur.rowcount > 0


def set_satellite_enabled(db, norad_id: int, enabled: bool) -> bool:
    with db._lock:
        cur = db.conn.execute(
            "UPDATE satellite_catalog SET enabled = ? WHERE norad_id = ?",
            (1 if enabled else 0, norad_id),
        )
        db.conn.commit()
    return cur.rowcount > 0


# ── Internals ─────────────────────────────────────────────────────────────────

def _upsert_catalog(db, entries: list[dict[str, Any]], source: str) -> int:
    now = _now_iso()
    count = 0
    with db._lock:
        for e in entries:
            norad = e.get("norad_cat_id") or e.get("norad_id")
            if norad is None:
                continue
            name = (e.get("name") or f"NORAD-{norad}")[:80]
            # Map SatNOGS transmitter fields if present
            downlink = e.get("downlink_hz") or _satnogs_downlink(e)
            mode = e.get("mode") or _satnogs_mode(e)
            db.conn.execute(
                """
                INSERT INTO satellite_catalog
                    (norad_id, name, downlink_hz, uplink_hz, mode,
                     min_elevation_deg, enabled, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(norad_id) DO UPDATE SET
                    name              = excluded.name,
                    downlink_hz       = COALESCE(excluded.downlink_hz, satellite_catalog.downlink_hz),
                    uplink_hz         = COALESCE(excluded.uplink_hz, satellite_catalog.uplink_hz),
                    mode              = COALESCE(excluded.mode, satellite_catalog.mode),
                    source            = excluded.source,
                    updated_at        = excluded.updated_at
                """,
                (
                    norad, name, downlink, e.get("uplink_hz"),
                    mode, e.get("min_elevation_deg", 5.0),
                    source, now,
                ),
            )
            count += 1
        db.conn.commit()
    return count


def _satnogs_downlink(e: dict) -> int | None:
    """Try to extract a downlink frequency from SatNOGS transmitter data."""
    transmitters = e.get("transmitters") or []
    for t in transmitters:
        f = t.get("downlink_low") or t.get("downlink_high")
        if f:
            try:
                return int(f)
            except (TypeError, ValueError):
                pass
    return None


def _satnogs_mode(e: dict) -> str | None:
    transmitters = e.get("transmitters") or []
    for t in transmitters:
        m = t.get("mode")
        if m:
            return str(m)[:16]
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
