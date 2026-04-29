# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
Satellite module — installer.

install() / uninstall() are called from /api/satellite/install and
/api/satellite/uninstall endpoints.  Jobs are tracked via KV keys so the
frontend can poll progress without blocking the HTTP response.

KV keys used:
  satellite_module_installed       "true" | "false"
  satellite_module_state           "idle" | "installing" | "installed" | "error" | "uninstalling"
  satellite_module_schema_version  "1"
  satellite_install_job_<uuid>_state   "running" | "done" | "error"
  satellite_install_job_<uuid>_log     accumulated text log
  satellite_install_job_<uuid>_started_at  ISO timestamp
"""

import asyncio
import importlib
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger("uvicorn.error")

_WHEELS_DIR = (
    Path(__file__).resolve().parents[3] / "data" / "satellite" / "wheels"
)

# ── Public API ────────────────────────────────────────────────────────────────

def is_installed(db) -> bool:
    return db.get_kv("satellite_module_installed") == "true"


def get_status(db) -> dict[str, Any]:
    from app.satellite.tle_manager import get_tle_badge
    installed = is_installed(db)
    state = db.get_kv("satellite_module_state") or ("installed" if installed else "idle")
    schema_v = db.get_kv("satellite_module_schema_version") or "0"
    badge = get_tle_badge(db) if installed else {"badge": "red", "age_days": None, "last_refresh": None}
    return {
        "installed": installed,
        "state": state,
        "schema_version": schema_v,
        "tle_badge": badge,
    }


async def install(db) -> str:
    """
    Kick off async install.  Returns job_id immediately.
    Caller polls GET /api/satellite/install/{job_id} for progress.
    """
    current = db.get_kv("satellite_module_state") or "idle"
    if current == "installing":
        raise RuntimeError("Installation already in progress")
    if current == "installed" or is_installed(db):
        raise RuntimeError("Module already installed")

    job_id = str(uuid.uuid4())
    db.set_kv("satellite_module_state", "installing")
    db.set_kv(f"satellite_install_job_{job_id}_state", "running")
    db.set_kv(f"satellite_install_job_{job_id}_started_at", _now_iso())
    db.set_kv(f"satellite_install_job_{job_id}_log", "Starting installation…\n")

    asyncio.create_task(_run_install(db, job_id), name=f"satellite_install_{job_id}")
    return job_id


def get_job_status(db, job_id: str) -> dict[str, Any] | None:
    state = db.get_kv(f"satellite_install_job_{job_id}_state")
    if state is None:
        return None
    return {
        "job_id": job_id,
        "state": state,
        "log": db.get_kv(f"satellite_install_job_{job_id}_log") or "",
        "started_at": db.get_kv(f"satellite_install_job_{job_id}_started_at"),
    }


async def uninstall(db, purge: bool = False) -> None:
    """
    Synchronously stop scheduler and optionally drop satellite tables.
    """
    from app.satellite.lifecycle import stop_scheduler

    db.set_kv("satellite_module_state", "uninstalling")
    await stop_scheduler()

    if purge:
        _drop_satellite_tables(db)
        db.set_kv("satellite_module_installed", "false")
        db.set_kv("satellite_module_state", "idle")
        _log.info("Satellite module uninstalled (purge=True).")
    else:
        db.set_kv("satellite_module_installed", "false")
        db.set_kv("satellite_module_state", "idle")
        _log.info("Satellite module disabled (purge=False, tables kept).")


# ── Async install worker ──────────────────────────────────────────────────────

async def _run_install(db, job_id: str) -> None:
    def log(msg: str):
        prev = db.get_kv(f"satellite_install_job_{job_id}_log") or ""
        db.set_kv(f"satellite_install_job_{job_id}_log", prev + msg + "\n")
        _log.info("[satellite install] %s", msg)

    try:
        # 1. Install pyorbital
        log("Installing pyorbital…")
        await _pip_install_pyorbital(log)

        # 2. Validate import
        log("Verifying pyorbital import…")
        try:
            importlib.invalidate_caches()
            importlib.import_module("pyorbital.orbital")
            log("pyorbital import OK.")
        except ImportError as exc:
            raise RuntimeError(f"pyorbital import failed after install: {exc}")

        # 3. Create DB tables
        log("Creating satellite database tables…")
        _create_satellite_tables(db)

        # 4. Load offline snapshots (catalog + TLEs)
        log("Loading offline TLE snapshot…")
        from app.satellite.tle_manager import load_snapshot_tles
        n_tles = load_snapshot_tles(db)
        log(f"  {n_tles} TLE entries loaded from snapshot.")

        log("Loading offline catalog snapshot…")
        from app.satellite.catalog_manager import load_snapshot_catalog
        n_cat = load_snapshot_catalog(db)
        log(f"  {n_cat} catalog entries loaded from snapshot.")

        # 5. Mark installed
        db.set_kv("satellite_module_schema_version", "1")
        db.set_kv("satellite_module_installed", "true")
        db.set_kv("satellite_module_state", "installed")
        db.set_kv(f"satellite_install_job_{job_id}_state", "done")
        log("Satellite module installed successfully.")

        # 6. Start scheduler without restart
        from app.satellite.lifecycle import start_scheduler
        await start_scheduler()

    except Exception as exc:
        db.set_kv("satellite_module_state", "error")
        db.set_kv(f"satellite_install_job_{job_id}_state", "error")
        log(f"ERROR: {exc}")
        _log.error("Satellite install failed: %s", exc, exc_info=True)


async def _pip_install_pyorbital(log) -> None:
    """
    Install pyorbital via pip, preferring local wheels for offline support.
    """
    loop = asyncio.get_event_loop()
    args = [sys.executable, "-m", "pip", "install", "--quiet", "pyorbital"]

    if _WHEELS_DIR.exists() and list(_WHEELS_DIR.glob("*.whl")):
        log(f"  Using local wheels from {_WHEELS_DIR}")
        args = [
            sys.executable, "-m", "pip", "install", "--quiet",
            "--no-index", f"--find-links={_WHEELS_DIR}", "pyorbital",
        ]

    log(f"  Running: {' '.join(args[2:])}")
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    output = (stdout or b"").decode(errors="replace").strip()
    if output:
        log(f"  pip output: {output[:500]}")
    if proc.returncode != 0:
        # Retry with PyPI if wheels failed
        if "--no-index" in args:
            log("  Local wheels failed, retrying from PyPI…")
            fallback_args = [sys.executable, "-m", "pip", "install", "--quiet", "pyorbital"]
            proc2 = await asyncio.create_subprocess_exec(
                *fallback_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out2, _ = await proc2.communicate()
            o2 = (out2 or b"").decode(errors="replace").strip()
            if o2:
                log(f"  pip output: {o2[:500]}")
            if proc2.returncode != 0:
                raise RuntimeError(f"pip install pyorbital failed (rc={proc2.returncode})")
        else:
            raise RuntimeError(f"pip install pyorbital failed (rc={proc.returncode})")


# ── DB schema ─────────────────────────────────────────────────────────────────

_SATELLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS satellite_catalog (
    norad_id          INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    tle_line1         TEXT,
    tle_line2         TEXT,
    tle_epoch         TEXT,
    tle_fetched_at    TEXT,
    downlink_hz       INTEGER,
    uplink_hz         INTEGER,
    mode              TEXT,
    min_elevation_deg REAL DEFAULT 5.0,
    enabled           INTEGER DEFAULT 1,
    source            TEXT DEFAULT 'satnogs',
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS satellite_passes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    norad_id      INTEGER NOT NULL,
    aos           TEXT NOT NULL,
    los           TEXT NOT NULL,
    max_elevation REAL NOT NULL,
    max_az        REAL,
    status        TEXT DEFAULT 'predicted',
    tle_epoch     TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_satellite_passes_aos ON satellite_passes(aos);

CREATE TABLE IF NOT EXISTS satellite_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    pass_id      INTEGER,
    norad_id     INTEGER,
    timestamp    TEXT NOT NULL,
    type         TEXT NOT NULL,
    frequency_hz INTEGER,
    doppler_hz   INTEGER,
    elevation    REAL,
    azimuth      REAL,
    snr_db       REAL,
    data         TEXT
);
CREATE INDEX IF NOT EXISTS idx_satellite_events_ts ON satellite_events(timestamp);
"""


def _create_satellite_tables(db) -> None:
    with db._lock:
        db.conn.executescript(_SATELLITE_SCHEMA)
        db.conn.commit()


def _drop_satellite_tables(db) -> None:
    with db._lock:
        db.conn.executescript(
            "DROP TABLE IF EXISTS satellite_events;"
            "DROP TABLE IF EXISTS satellite_passes;"
            "DROP TABLE IF EXISTS satellite_catalog;"
        )
        db.conn.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
