# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
Satellite module — TLE manager.

Responsibilities:
- Fetch TLEs from Celestrak (with graceful timeout/fallback to snapshot).
- Cache parsed TLEs in the satellite_catalog DB table.
- Compute and expose the TLE freshness badge (green / yellow / red).
- Import TLEs from a manually uploaded file (via validators.parse_tle_text).
"""

import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

_log = logging.getLogger("uvicorn.error")

_CELESTRAK_URL = (
    "https://celestrak.org/NORAD/elements/gp.php?GROUP=amateur&FORMAT=TLE"
)
# Additional Celestrak GROUPs to fetch so we cover weather sats (NOAA APT,
# Meteor LRPT, GOES/Elektro/FengYun HRIT) and other receivable cubesats that
# are not in the 'amateur' group. Order matters: later groups overwrite
# earlier entries for duplicate NORAD ids (which is fine — TLEs are the
# same regardless of group).
_CELESTRAK_EXTRA_URLS = [
    "https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=TLE",
    "https://celestrak.org/NORAD/elements/gp.php?GROUP=noaa&FORMAT=TLE",
    "https://celestrak.org/NORAD/elements/gp.php?GROUP=goes&FORMAT=TLE",
    "https://celestrak.org/NORAD/elements/gp.php?GROUP=cubesat&FORMAT=TLE",
    "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=TLE",
]
_TLE_SNAPSHOT = (
    Path(__file__).resolve().parents[3] / "data" / "satellite" / "tle_amateur.txt"
)

# Badge thresholds (days)
_BADGE_GREEN_DAYS  = 7
_BADGE_YELLOW_DAYS = 21


# ── Public API ────────────────────────────────────────────────────────────────

def get_tle_badge(db) -> dict[str, Any]:
    """Return badge dict: {"badge": "green|yellow|red", "age_days": int, "last_refresh": str|None}."""
    last_ok = db.get_kv("satellite_tle_last_refresh_ok")
    if not last_ok:
        return {"badge": "red", "age_days": None, "last_refresh": None}

    try:
        ts = datetime.fromisoformat(last_ok)
        age = (datetime.now(timezone.utc) - ts).days
    except ValueError:
        return {"badge": "red", "age_days": None, "last_refresh": last_ok}

    if age <= _BADGE_GREEN_DAYS:
        badge = "green"
    elif age <= _BADGE_YELLOW_DAYS:
        badge = "yellow"
    else:
        badge = "red"
    return {"badge": badge, "age_days": age, "last_refresh": last_ok}


async def refresh_tles(db) -> dict[str, Any]:
    """
    Fetch TLEs from Celestrak.  On failure, keeps existing cache and sets error KV.
    Returns {"ok": bool, "count": int, "error": str|None}.
    """
    import httpx
    from app.satellite.validators import parse_tle_text
    from app.core import connectivity

    # Skip the network round-trip when the connectivity probe says we are
    # offline.  Avoids a 15 s stall on every refresh while disconnected;
    # the existing cache + freshness badge already tell the operator what
    # is going on.  Probe state may be None on cold start — only skip when
    # an explicit offline result is known.
    if connectivity.get_status().get("online") is False:
        msg = "offline (connectivity probe): keeping cached TLEs"
        _log.info("TLE refresh skipped — %s", msg)
        db.set_kv("satellite_tle_last_refresh_error", _now_iso())
        return {"ok": False, "count": 0, "error": msg}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_CELESTRAK_URL)
            resp.raise_for_status()
            raw = resp.content
            # Fetch additional groups; tolerate per-group failures so a single
            # 503 from Celestrak does not wipe out the entire refresh.
            extra_chunks: list[bytes] = []
            for url in _CELESTRAK_EXTRA_URLS:
                try:
                    r = await client.get(url)
                    r.raise_for_status()
                    extra_chunks.append(r.content)
                except Exception as exc:
                    _log.warning("TLE extra group fetch failed (%s): %s", url, exc)
    except Exception as exc:
        err = str(exc)
        _log.warning("TLE fetch failed (Celestrak): %s", err)
        db.set_kv("satellite_tle_last_refresh_error", _now_iso())
        return {"ok": False, "count": 0, "error": err}

    try:
        entries = parse_tle_text(raw)
        # Append extra groups; _upsert_tles deduplicates via ON CONFLICT
        # (norad_id) so we can simply concatenate.
        for chunk in extra_chunks:
            try:
                entries.extend(parse_tle_text(chunk))
            except Exception as exc:
                _log.warning("TLE extra group parse failed: %s", exc)
    except Exception as exc:
        db.set_kv("satellite_tle_last_refresh_error", _now_iso())
        return {"ok": False, "count": 0, "error": f"Parse error: {exc}"}

    _upsert_tles(db, entries, source="celestrak")
    db.set_kv("satellite_tle_last_refresh_ok", _now_iso())
    _log.info("TLE refresh OK: %d entries from Celestrak.", len(entries))
    return {"ok": True, "count": len(entries), "error": None}


async def import_tles_from_bytes(db, raw: bytes) -> dict[str, Any]:
    """
    Import TLEs from manually uploaded bytes.
    Returns {"ok": bool, "imported": int, "ignored": int, "error": str|None}.
    """
    from app.satellite.validators import parse_tle_text, ValidationError

    try:
        entries = parse_tle_text(raw)
    except ValidationError as exc:
        return {"ok": False, "imported": 0, "ignored": 0, "error": str(exc)}

    imported = _upsert_tles(db, entries, source="manual")
    db.set_kv("satellite_tle_last_refresh_ok", _now_iso())
    return {"ok": True, "imported": imported, "ignored": len(entries) - imported, "error": None}


def load_snapshot_tles(db) -> int:
    """
    Load the bundled offline TLE snapshot into the DB.
    Called by installer when network is unavailable.
    Returns number of entries loaded.
    """
    from app.satellite.validators import parse_tle_text, ValidationError

    if not _TLE_SNAPSHOT.exists():
        _log.warning("TLE snapshot file not found: %s", _TLE_SNAPSHOT)
        return 0
    try:
        raw = _TLE_SNAPSHOT.read_bytes()
        entries = parse_tle_text(raw)
    except (ValidationError, OSError) as exc:
        _log.warning("TLE snapshot load error: %s", exc)
        return 0

    count = _upsert_tles(db, entries, source="snapshot")
    _log.info("TLE snapshot loaded: %d entries.", count)
    return count


# ── Internals ─────────────────────────────────────────────────────────────────

def _upsert_tles(db, entries: list[dict], source: str) -> int:
    """Upsert TLE lines into satellite_catalog.  Returns number of rows upserted."""
    now = _now_iso()
    # Parse epoch from TLE line 1 (field: epoch, columns 18-32, YYDDD.DDDDDDDD)
    count = 0
    with db._lock:
        for entry in entries:
            norad = _norad_from_line1(entry["line1"])
            if norad is None:
                continue
            epoch_iso = _tle_epoch_iso(entry["line1"])
            db.conn.execute(
                """
                INSERT INTO satellite_catalog
                    (norad_id, name, tle_line1, tle_line2, tle_epoch, tle_fetched_at,
                     source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(norad_id) DO UPDATE SET
                    name        = excluded.name,
                    tle_line1   = excluded.tle_line1,
                    tle_line2   = excluded.tle_line2,
                    tle_epoch   = excluded.tle_epoch,
                    tle_fetched_at = excluded.tle_fetched_at,
                    source      = excluded.source,
                    updated_at  = excluded.updated_at
                """,
                (norad, entry["name"], entry["line1"], entry["line2"],
                 epoch_iso, now, source, now),
            )
            count += 1
        db.conn.commit()
    return count


def _norad_from_line1(line1: str) -> int | None:
    try:
        return int(line1[2:7].strip())
    except (ValueError, IndexError):
        return None


def _tle_epoch_iso(line1: str) -> str | None:
    """Convert TLE epoch (YYDDD.fraction) in columns 18-32 to ISO 8601 UTC string."""
    try:
        epoch_str = line1[18:32].strip()
        year_2d = int(epoch_str[:2])
        year = (2000 + year_2d) if year_2d < 57 else (1900 + year_2d)
        day_frac = float(epoch_str[2:])
        day = int(day_frac)
        frac = day_frac - day
        dt = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day - 1, seconds=frac * 86400)
        return dt.isoformat()
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
