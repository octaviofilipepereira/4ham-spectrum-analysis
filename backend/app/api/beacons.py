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
GET  /api/beacons/heatmap         → 18×5 aggregated activity over last N hours
GET  /api/beacons/observations    → paginated observation history (SQLite)
GET  /api/beacons/map/contacts    → beacon-native propagation map contacts
GET  /api/beacons/propagation_summary → beacon-native propagation score summary
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.core.ionospheric import ionospheric_cache
from app.dependencies import state
from app.dependencies.helpers import callsign_to_dxcc, maidenhead_to_latlon
from app.beacons.catalog import BANDS, BEACONS, beacon_at, current_cycle_window, current_slot_index
from app.beacons.propagation import build_beacon_map_contacts, build_beacon_propagation_summary
from app.beacons.public_payloads import public_beacon_heatmap_cell, public_beacon_observation

router = APIRouter()

_TIME_SYNC_OFFSET_HEALTHY_MS = 500.0
_TIME_SYNC_OFFSET_OFFLINE_MS = 2000.0
_TIME_SYNC_ROOT_DISTANCE_HEALTHY_MS = 1000.0
_TIME_SYNC_ROOT_DISTANCE_OFFLINE_MS = 5000.0
_TIME_SYNC_PROBE_TIMEOUT_S = 3.0
_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_DURATION_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(us|ms|s|min|h|d)")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _command_output(args: list[str]) -> str | None:
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            check=False,
            text=True,
            timeout=_TIME_SYNC_PROBE_TIMEOUT_S,
            env=env,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or "").strip()
    return output or None


def _resolve_station_coords() -> tuple[float, float]:
    settings = state.db.get_settings()
    station = settings.get("station") or {}
    locator = str(station.get("locator") or "").strip().upper()
    station_callsign = str(station.get("callsign") or "").strip().upper()

    station_lat: float | None = None
    station_lon: float | None = None
    if locator:
        pos = maidenhead_to_latlon(locator)
        if pos:
            station_lat, station_lon = pos
    if station_lat is None and station_callsign:
        dxcc = callsign_to_dxcc(station_callsign)
        if dxcc:
            station_lat = dxcc.get("lat")
            station_lon = dxcc.get("lon")
    if station_lat is None or station_lon is None:
        station_lat, station_lon = 39.5, -8.0
    return float(station_lat), float(station_lon)


def _expected_band_state(ionospheric: dict[str, Any], band_name: str) -> str:
    band_payload = ((ionospheric or {}).get("bands") or {}).get(band_name) or {}
    return str(band_payload.get("status") or "Unknown")


def _band_agreement(observed_state: str, expected_state: str) -> str:
    observed = str(observed_state or "").strip()
    expected = str(expected_state or "").strip()
    if observed in {"", "No data"} or expected in {"", "Unknown"}:
        return "unknown"
    if observed in {"Excellent", "Good"} and expected == "Open":
        return "aligned"
    if observed == "Fair" and expected in {"Open", "Marginal"}:
        return "mixed"
    if observed == "Poor" and expected in {"Closed", "Absorbed"}:
        return "aligned"
    if observed == "Poor" and expected == "Marginal":
        return "mixed"
    if observed in {"Excellent", "Good"} and expected in {"Marginal", "Closed", "Absorbed"}:
        return "divergent"
    if observed == "Fair" and expected in {"Closed", "Absorbed"}:
        return "divergent"
    return "mixed"


def _score_to_confidence(score: float) -> str:
    if score >= 70.0:
        return "high"
    if score >= 40.0:
        return "moderate"
    return "low"


def _build_beacon_reading(propagation: dict[str, Any], ionospheric: dict[str, Any]) -> dict[str, Any]:
    band_rows: list[dict[str, Any]] = []
    agreements: list[str] = []
    for entry in propagation.get("bands") or []:
        band_name = str(entry.get("band") or "").strip()
        if band_name not in {band.name for band in BANDS}:
            continue
        observed_state = str(entry.get("state") or "No data")
        expected_state = _expected_band_state(ionospheric, band_name)
        agreement = _band_agreement(observed_state, expected_state)
        band_rows.append({
            "band": band_name,
            "observed_state": observed_state,
            "expected_state": expected_state,
            "agreement": agreement,
        })
        if agreement != "unknown":
            agreements.append(agreement)

    if agreements and all(item == "aligned" for item in agreements):
        state_name = "aligned"
    elif any(item == "divergent" for item in agreements):
        state_name = "divergent"
    elif agreements:
        state_name = "mixed"
    else:
        state_name = "unknown"

    overall_score = float(((propagation.get("overall") or {}).get("score") or 0.0))
    confidence = _score_to_confidence(overall_score)
    if state_name == "aligned":
        summary = "Beacon observations broadly align with the current ionospheric estimate."
    elif state_name == "divergent":
        summary = "Beacon observations diverge from the current ionospheric estimate on one or more bands."
    elif state_name == "mixed":
        summary = "Beacon observations are mixed versus the current ionospheric estimate."
    else:
        summary = "Not enough Beacon or ionospheric context is available to assess agreement."

    return {
        "state": state_name,
        "confidence": confidence,
        "summary": summary,
        "bands": band_rows,
    }


def _forecast_state_from_expected(expected_state: str) -> str:
    if expected_state == "Open":
        return "Good"
    if expected_state == "Marginal":
        return "Fair"
    if expected_state in {"Closed", "Absorbed"}:
        return "Poor"
    return "No data"


def _build_beacon_nowcast(
    propagation: dict[str, Any],
    ionospheric: dict[str, Any],
    forecast_window_minutes: int,
) -> dict[str, Any]:
    bands: list[dict[str, Any]] = []
    for entry in propagation.get("bands") or []:
        band_name = str(entry.get("band") or "").strip()
        expected_state = _expected_band_state(ionospheric, band_name)
        observed_state = str(entry.get("state") or "No data")
        forecast_state = observed_state if observed_state != "No data" else _forecast_state_from_expected(expected_state)
        confidence = "moderate" if expected_state in {"Open", "Marginal", "Closed", "Absorbed"} else "low"
        bands.append({
            "band": band_name,
            "forecast_state": forecast_state,
            "confidence": confidence,
        })

    overall_state = str(((propagation.get("overall") or {}).get("state") or "No data"))
    if overall_state in {"Excellent", "Good"}:
        summary = "Recent Beacon activity suggests current conditions are likely to hold in the short term."
    elif overall_state == "Fair":
        summary = "Recent Beacon activity suggests mixed short-term conditions across the monitored bands."
    else:
        summary = "Recent Beacon activity suggests weak short-term conditions across the monitored bands."

    return {
        "kind": "nowcast",
        "valid_for_minutes": max(30, int(forecast_window_minutes or 180)),
        "confidence": _score_to_confidence(float(((propagation.get("overall") or {}).get("score") or 0.0))),
        "summary": summary,
        "bands": bands,
    }


def _build_recent_activity_summary(rows: list[dict[str, Any]], hours: float) -> dict[str, Any]:
    cell: dict[tuple[int, str], dict[str, Any]] = {}
    for row in rows:
        b_idx = row.get("beacon_index")
        if b_idx is None:
            continue
        public_row = public_beacon_heatmap_cell(row)
        if public_row is not None:
            cell[(int(b_idx), row["band_name"])] = public_row

    matrix: list[list[dict[str, Any] | None]] = []
    for slot_idx in range(18):
        row_data: list[dict[str, Any] | None] = []
        for band in BANDS:
            row_data.append(cell.get((slot_idx, band.name)))
        matrix.append(row_data)

    return {
        "hours": hours,
        "bands": [band.name for band in BANDS],
        "beacons": [beacon.callsign for beacon in BEACONS],
        "matrix": matrix,
    }


def _build_kpis(heatmap_rows: list[dict[str, Any]], propagation: dict[str, Any]) -> dict[str, Any]:
    monitored_slots = sum(int(row.get("total_slots") or 0) for row in heatmap_rows)
    detected_slots = sum(int(row.get("detections") or 0) for row in heatmap_rows)
    detected_beacons = len({
        int(row.get("beacon_index"))
        for row in heatmap_rows
        if int(row.get("detections") or 0) > 0 and row.get("beacon_index") is not None
    })
    best_band = None
    monitored_bands = [row for row in (propagation.get("bands") or []) if int(row.get("events") or 0) > 0]
    if monitored_bands:
        top_band = max(monitored_bands, key=lambda row: float(row.get("score") or 0.0))
        best_band = {
            "band": top_band.get("band"),
            "score": float(top_band.get("score") or 0.0),
            "state": top_band.get("state") or "No data",
        }
    overall = propagation.get("overall") or {}
    return {
        "monitored_slots": monitored_slots,
        "detected_slots": detected_slots,
        "detected_beacons": detected_beacons,
        "best_band": best_band,
        "global_score": float(overall.get("score") or 0.0),
        "global_state": overall.get("state") or "No data",
    }


def _duration_to_ms(value: str | None) -> float | None:
    if value is None:
        return None
    base = str(value).split("(", 1)[0].replace(",", "").strip()
    if not base:
        return None
    sign = -1.0 if base.startswith("-") else 1.0
    if base[:1] in "+-":
        base = base[1:].strip()
    matches = _DURATION_RE.findall(base)
    if not matches:
        try:
            return sign * float(base)
        except ValueError:
            return None
    scale = {
        "us": 0.001,
        "ms": 1.0,
        "s": 1000.0,
        "min": 60_000.0,
        "h": 3_600_000.0,
        "d": 86_400_000.0,
    }
    total = 0.0
    for number, unit in matches:
        total += float(number) * scale[unit]
    return sign * total


def _split_server_descriptor(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    candidate = value.strip()
    match = re.match(r"(.+?)\s+\((.+)\)$", candidate)
    if match:
        left = match.group(1).strip()
        right = match.group(2).strip()
        if _IPV4_RE.match(left) and not _IPV4_RE.match(right):
            return right, left
        if _IPV4_RE.match(right) and not _IPV4_RE.match(left):
            return left, right
        return left, right
    if _IPV4_RE.match(candidate):
        return None, candidate
    return candidate, None


def _parse_timedatectl_status(text: str, info: dict[str, Any]) -> None:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "system clock synchronized":
            info["synchronized"] = value.lower() == "yes"
        elif key == "ntp service":
            info["ntp_service"] = value.lower()
        elif key == "time zone":
            info["timezone"] = value.split()[0]


def _parse_timedatectl_timesync_status(text: str, info: dict[str, Any]) -> None:
    info["source"] = "timedatectl"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "server":
            name, address = _split_server_descriptor(value)
            if name:
                info["server_name"] = name
            if address:
                info["server_address"] = address
        elif key == "offset":
            info["offset_ms"] = _duration_to_ms(value)
        elif key == "jitter":
            info["jitter_ms"] = _duration_to_ms(value)
        elif key == "root distance":
            info["root_distance_ms"] = _duration_to_ms(value)
        elif key == "leap":
            info["leap_status"] = value.lower()


def _parse_chrony_tracking(text: str, info: dict[str, Any]) -> None:
    info["source"] = "chrony"
    root_delay_ms = None
    root_dispersion_ms = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "reference id":
            name, address = _split_server_descriptor(value)
            if name:
                info["server_name"] = name
            if address:
                info["server_address"] = address
        elif key == "last offset":
            info["offset_ms"] = _duration_to_ms(value)
        elif key == "rms offset" and info.get("jitter_ms") is None:
            info["jitter_ms"] = _duration_to_ms(value)
        elif key == "root delay":
            root_delay_ms = _duration_to_ms(value)
        elif key == "root dispersion":
            root_dispersion_ms = _duration_to_ms(value)
        elif key == "leap status":
            info["leap_status"] = value.lower()
    if root_delay_ms is not None or root_dispersion_ms is not None:
        info["root_distance_ms"] = max(
            root_delay_ms if root_delay_ms is not None else 0.0,
            root_dispersion_ms if root_dispersion_ms is not None else 0.0,
        )


def _parse_chrony_sources(text: str, info: dict[str, Any]) -> None:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("^*"):
            continue
        parts = line[2:].split()
        if not parts:
            continue
        name, address = _split_server_descriptor(parts[0])
        if name:
            info["server_name"] = name
        if address:
            info["server_address"] = address
        return


def _time_sync_result(reason_code: str, message: str, state_name: str, info: dict[str, Any]) -> dict[str, Any]:
    result = dict(info)
    result["state"] = state_name
    result["can_start"] = state_name == "healthy"
    result["reason_code"] = reason_code
    result["message"] = message
    return result


def _classify_time_sync(info: dict[str, Any]) -> dict[str, Any]:
    result = {
        "checked_at_utc": info.get("checked_at_utc") or _now_iso(),
        "source": info.get("source") or "unknown",
        "synchronized": info.get("synchronized"),
        "ntp_service": info.get("ntp_service") or "unknown",
        "timezone": info.get("timezone") or "",
        "server_name": info.get("server_name") or "",
        "server_address": info.get("server_address") or "",
        "offset_ms": info.get("offset_ms"),
        "jitter_ms": info.get("jitter_ms"),
        "root_distance_ms": info.get("root_distance_ms"),
        "leap_status": info.get("leap_status") or "unknown",
    }

    leap = str(result["leap_status"] or "unknown").strip().lower()
    offset_ms = result.get("offset_ms")
    root_distance_ms = result.get("root_distance_ms")
    ntp_service = str(result.get("ntp_service") or "unknown").strip().lower()
    synchronized = result.get("synchronized")
    has_server = bool(result.get("server_name") or result.get("server_address"))
    has_quality_metrics = offset_ms is not None or root_distance_ms is not None

    if synchronized is False:
        return _time_sync_result(
            "not_synchronized",
            "System clock is not synchronized.",
            "offline",
            result,
        )

    if ntp_service in {"inactive", "failed", "disabled", "no"}:
        return _time_sync_result(
            "ntp_inactive",
            "NTP service is not active.",
            "offline",
            result,
        )

    if leap not in {"unknown", "normal"}:
        return _time_sync_result(
            "leap_not_normal",
            "Time source reported a non-normal leap state.",
            "offline",
            result,
        )

    if offset_ms is not None:
        if abs(offset_ms) > _TIME_SYNC_OFFSET_OFFLINE_MS:
            return _time_sync_result(
                "offset_too_high",
                "Clock offset is too high for reliable 10-second UTC slots.",
                "offline",
                result,
            )
        if abs(offset_ms) > _TIME_SYNC_OFFSET_HEALTHY_MS:
            return _time_sync_result(
                "offset_too_high",
                "Clock offset is degraded for reliable 10-second UTC slots.",
                "degraded",
                result,
            )

    if root_distance_ms is not None:
        if root_distance_ms > _TIME_SYNC_ROOT_DISTANCE_OFFLINE_MS:
            return _time_sync_result(
                "root_distance_too_high",
                "Time source distance is too high for reliable UTC slot alignment.",
                "offline",
                result,
            )
        if root_distance_ms > _TIME_SYNC_ROOT_DISTANCE_HEALTHY_MS:
            return _time_sync_result(
                "root_distance_too_high",
                "Time source distance is degraded for reliable UTC slot alignment.",
                "degraded",
                result,
            )

    if synchronized is True and ntp_service == "active" and has_server and has_quality_metrics:
        return _time_sync_result(
            "ok",
            "Host UTC time validated. Beacon Analysis can start.",
            "healthy",
            result,
        )

    if synchronized is True and ntp_service == "active" and not has_server:
        return _time_sync_result(
            "no_active_server",
            "No active NTP server was detected.",
            "degraded",
            result,
        )

    if synchronized is True and ntp_service == "active":
        return _time_sync_result(
            "probe_partial",
            "Time sync probe is incomplete. Beacon Analysis start is blocked.",
            "degraded",
            result,
        )

    return _time_sync_result(
        "probe_unavailable",
        "Time sync probe is unavailable on this host. Beacon Analysis start is blocked.",
        "offline",
        result,
    )


def _probe_time_sync() -> dict[str, Any]:
    info: dict[str, Any] = {
        "checked_at_utc": _now_iso(),
        "source": "unknown",
        "synchronized": None,
        "ntp_service": "unknown",
        "timezone": "",
        "server_name": "",
        "server_address": "",
        "offset_ms": None,
        "jitter_ms": None,
        "root_distance_ms": None,
        "leap_status": "unknown",
    }

    timedatectl_status = _command_output(["timedatectl", "status"])
    if timedatectl_status:
        _parse_timedatectl_status(timedatectl_status, info)
        info["source"] = "timedatectl"

    timedatectl_timesync = _command_output(["timedatectl", "timesync-status"])
    if timedatectl_timesync:
        _parse_timedatectl_timesync_status(timedatectl_timesync, info)
        return _classify_time_sync(info)

    chrony_tracking = _command_output(["chronyc", "tracking"])
    if chrony_tracking:
        _parse_chrony_tracking(chrony_tracking, info)
        chrony_sources = _command_output(["chronyc", "sources", "-v"])
        if chrony_sources:
            _parse_chrony_sources(chrony_sources, info)

    return _classify_time_sync(info)


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
    time_sync = _probe_time_sync()
    return {
        "scheduler": snapshot,
        "catalog": {
            "beacons": len(BEACONS),
            "bands": len(BANDS),
            "active_beacons": sum(1 for b in BEACONS if b.status == "active"),
        },
        "time_sync": time_sync,
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

    time_sync = _probe_time_sync()
    if not time_sync.get("can_start"):
        raise HTTPException(
            status_code=412,
            detail={
                "code": "beacon_time_sync_unhealthy",
                "message": time_sync.get("message") or "Time sync validation failed.",
                "time_sync": time_sync,
            },
        )

    requested_bands = bands if isinstance(bands, list) else None

    band_map = {b.name: b for b in BANDS}
    if requested_bands is None:
        selected = list(BANDS)
    else:
        selected = [band_map[n] for n in requested_bands if n in band_map]
        if not selected:
            raise HTTPException(status_code=400, detail="no_valid_bands")

    sched._bands = selected
    sched._band_index = 0
    sched._slots_on_band = 0

    # Register dedicated IQ listener before starting the scheduler
    # (avoids stealing from the waterfall's _spectrum_queue)
    if state.scan_engine and state.beacon_iq_queue:
        state.scan_engine.register_iq_listener(state.beacon_iq_queue)

    started = await sched.start()
    return {"ok": started, **sched.snapshot()}


@router.post("/stop")
async def beacon_stop() -> dict[str, Any]:
    """Stop the NCDXF beacon scheduler."""
    sched = _scheduler()
    if sched is None:
        raise HTTPException(status_code=503, detail="beacon_scheduler_unavailable")
    stopped = await sched.stop()
    
    # Unregister IQ listener when stopped (zero cost when inactive)
    if state.scan_engine and state.beacon_iq_queue:
        state.scan_engine.unregister_iq_listener(state.beacon_iq_queue)
    
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
    for that cell within the current UTC cycle (or null if the slot has not
    been visited yet in this cycle).

    Also returns the current slot index for the frontend highlight.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    slot_idx = current_slot_index(now)
    cycle_start, cycle_end = current_cycle_window(now)

    # Pull enough recent rows to cover the current cycle, then discard any
    # observations that belong to earlier/later cycles.
    rows = state.db.get_beacon_observations(limit=450)

    # Build lookup: (beacon_index, band_name) → most recent observation in the
    # current cycle. Use beacon_index (NCDXF rotation order) NOT slot_index —
    # the schedule offsets between bands so the same row maps to different
    # slots.
    cell: dict[tuple[int, str], dict] = {}
    for row in rows:
        try:
            slot_start = datetime.fromisoformat(row["slot_start_utc"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (cycle_start <= slot_start < cycle_end):
            continue
        b_idx = row.get("beacon_index")
        if b_idx is None:
            b_idx = (row.get("slot_index") or 0) % 18
        key = (b_idx, row["band_name"])
        if key not in cell:
            public_row = public_beacon_observation(row)
            if public_row is not None:
                cell[key] = public_row

    # Build 18×5 matrix
    matrix: list[list[dict | None]] = []
    for s in range(18):
        row_data = []
        for band in BANDS:
            row_data.append(cell.get((s, band.name)))
        matrix.append(row_data)

    return {
        "current_slot_index": slot_idx,
        "cycle_start_utc": cycle_start.isoformat(),
        "cycle_end_utc": cycle_end.isoformat(),
        "bands": [b.name for b in BANDS],
        "beacons": [b.callsign for b in BEACONS],
        "matrix": matrix,
    }


# ── Observations ──────────────────────────────────────────────────────────────

@router.get("/heatmap")
async def beacon_heatmap(
    hours: float = Query(default=2.0, ge=0.1, le=72.0),
) -> dict[str, Any]:
    """Aggregated 18×5 activity heatmap over the last ``hours`` hours.

    Distinct from ``/matrix`` (which reflects only the live current state).
    Each cell carries detection counts so the UI can show recent propagation
    history without lying about the *current* slot.
    """
    rows = state.db.get_beacon_heatmap(hours=hours)
    cell: dict[tuple[int, str], dict] = {}
    for row in rows:
        b_idx = row.get("beacon_index")
        if b_idx is None:
            continue
        public_row = public_beacon_heatmap_cell(row)
        if public_row is not None:
            cell[(int(b_idx), row["band_name"])] = public_row

    matrix: list[list[dict | None]] = []
    for s in range(18):
        row_data: list[dict | None] = []
        for band in BANDS:
            row_data.append(cell.get((s, band.name)))
        matrix.append(row_data)

    return {
        "hours": hours,
        "bands": [b.name for b in BANDS],
        "beacons": [b.callsign for b in BEACONS],
        "matrix": matrix,
    }


@router.get("/observations")
async def beacon_observations(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    band: str | None = Query(default=None),
    callsign: str | None = Query(default=None),
    detected_only: bool = Query(default=False),
    hours: float | None = Query(default=None, ge=0.1, le=72.0),
) -> dict[str, Any]:
    """Paginated beacon observation history."""
    rows = state.db.get_beacon_observations(
        limit=limit,
        offset=offset,
        band=band,
        callsign=callsign,
        detected_only=detected_only,
        hours=hours,
    )
    public_rows = [row for row in (public_beacon_observation(row) for row in rows) if row is not None]
    return {"observations": public_rows, "count": len(public_rows), "offset": offset}


@router.get("/analytics/overview")
async def beacon_analytics_overview(
    heatmap_hours: float = Query(default=12.0, ge=1.0, le=72.0),
    propagation_window_minutes: int = Query(default=180, ge=30, le=1440),
    forecast_window_minutes: int = Query(default=180, ge=30, le=360),
    limit: int = Query(default=10000, ge=100, le=10000),
) -> dict[str, Any]:
    heatmap_rows = state.db.get_beacon_heatmap(hours=heatmap_hours)
    propagation_rows = state.db.get_beacon_observations(
        limit=limit,
        hours=max(0.1, propagation_window_minutes / 60.0),
        detected_only=False,
    )
    propagation = build_beacon_propagation_summary(propagation_rows, propagation_window_minutes)
    station_lat, station_lon = _resolve_station_coords()
    ionospheric = ionospheric_cache.get_summary(latitude=station_lat, longitude=station_lon)
    reading = _build_beacon_reading(propagation, ionospheric)
    forecast = _build_beacon_nowcast(propagation, ionospheric, forecast_window_minutes)

    return {
        "status": "ok",
        "kind": "beacon_analytics",
        "source_kind": "live",
        "generated_at_utc": _now_iso(),
        "snapshot_captured_at_utc": None,
        "staleness_seconds": 0,
        "windows": {
            "heatmap_hours": heatmap_hours,
            "propagation_window_minutes": propagation_window_minutes,
            "forecast_window_minutes": forecast_window_minutes,
        },
        "freshness": {
            "label": "fresh",
            "push_interval_seconds": None,
            "warning": None,
        },
        "kpis": _build_kpis(heatmap_rows, propagation),
        "recent_activity": _build_recent_activity_summary(heatmap_rows, heatmap_hours),
        "propagation": propagation,
        "ionospheric": ionospheric,
        "reading": reading,
        "forecast": forecast,
    }


@router.get("/map/contacts")
async def beacon_map_contacts(
    window_minutes: int = Query(default=60, ge=10, le=1440),
    limit: int = Query(default=10000, ge=100, le=10000),
) -> dict[str, Any]:
    """Return Beacon detections as map contacts without affecting the generic map API."""
    rows = state.db.get_beacon_observations(
        limit=limit,
        hours=max(0.1, window_minutes / 60.0),
        detected_only=True,
    )
    settings = state.db.get_settings()
    return build_beacon_map_contacts(rows, settings, window_minutes)


@router.get("/propagation_summary")
async def beacon_propagation_summary(
    window_minutes: int = Query(default=60, ge=10, le=1440),
    limit: int = Query(default=10000, ge=100, le=10000),
) -> dict[str, Any]:
    """Return Beacon-native propagation scores per band plus a global median score."""
    rows = state.db.get_beacon_observations(
        limit=limit,
        hours=max(0.1, window_minutes / 60.0),
        detected_only=False,
    )
    return build_beacon_propagation_summary(rows, window_minutes)
