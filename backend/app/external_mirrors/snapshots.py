# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
"""
Endpoint snapshot bundler for external mirror pushes.

The receiver runs on plain shared hosting (PHP + MySQL) and cannot execute
the heavy aggregations performed by the live Python endpoints.  To still
serve the same JSON to the public dashboard, the backend pre-computes the
relevant endpoint responses *here* on every push and embeds them into the
mirror payload under ``payload["snapshots"]``.

Each entry maps an endpoint key (matching the path the dashboard fetches)
to the literal JSON body the live endpoint would have produced at the
moment of the snapshot.  The receiver UPSERTs each entry into
``mirror_endpoint_snapshots`` and PHP shims serve it back verbatim.

This keeps the public dashboard byte-for-byte equivalent to the live one
without re-implementing any business logic in PHP, and avoids exposing
the home backend to the internet (push-only architecture is preserved).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)


# Endpoint keys ─ MUST match the path components used by the PHP shims.
ENDPOINT_VERSION = "version"
ENDPOINT_SCAN_STATUS = "scan/status"
ENDPOINT_SETTINGS = "settings"
ENDPOINT_MAP_IONOSPHERIC = "map/ionospheric"
ENDPOINT_MAP_CONTACTS = "map/contacts"
ENDPOINT_ANALYTICS_ACADEMIC = "analytics/academic"
# Per-window pre-computed academic snapshots so the dashboard period
# selector (1h / 24h / 7d / 30d) sees the correct bucketing instead of
# always slicing the 7d hourly snapshot.
ENDPOINT_ANALYTICS_ACADEMIC_1H = "analytics/academic/1h"
ENDPOINT_ANALYTICS_ACADEMIC_24H = "analytics/academic/24h"
ENDPOINT_ANALYTICS_ACADEMIC_7D = "analytics/academic/7d"
ENDPOINT_ANALYTICS_ACADEMIC_30D = "analytics/academic/30d"
ENDPOINT_BEACON_STATUS = "beacons/status"
ENDPOINT_BEACON_ANALYTICS_OVERVIEW = "beacons/analytics/overview"
ENDPOINT_BEACON_OBSERVATIONS = "beacons/observations"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(label: str, fn):
    """Run ``fn()`` and swallow exceptions, logging them.

    A single failing snapshot must never break the whole push — the
    receiver will keep serving the previous snapshot for that endpoint.
    """
    try:
        return fn()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Snapshot %s failed: %s", label, exc)
        return None


def _snapshot_version() -> Dict[str, Any]:
    from ..version import APP_VERSION

    return {"version": APP_VERSION, "app_version": APP_VERSION}


def _snapshot_scan_status() -> Dict[str, Any]:
    from ..dependencies import state

    payload = dict(state.scan_state)
    try:
        payload["engine"] = state.scan_engine.status()
    except Exception:
        payload["engine"] = None
    if getattr(state, "scan_rotation", None):
        try:
            payload["rotation"] = state.scan_rotation.status()
        except Exception:
            pass
    return payload


def _snapshot_settings() -> Dict[str, Any]:
    """Replicates GET /api/settings body without auth/runtime-only branches.

    Mirrors backend/app/api/settings.py::get_settings — public surface only;
    we strip ``auth.password_configured`` etc. to a safe, public projection
    so the dashboard can render station/modes/summary without leaking
    operator-side information.
    """
    from ..dependencies import state

    settings = state.db.get_settings()
    modes = settings.get("modes") or {}
    settings["modes"] = {
        "ft8": bool(modes.get("ft8", state.default_modes["ft8"])),
        "ft4": bool(modes.get("ft4", state.default_modes["ft4"])),
        "wspr": bool(modes.get("wspr", state.default_modes["wspr"])),
        "aprs": bool(modes.get("aprs", state.default_modes["aprs"])),
        "cw": bool(modes.get("cw", state.default_modes["cw"])),
        "ssb": bool(modes.get("ssb", state.default_modes["ssb"])),
    }
    if "summary" not in settings:
        settings["summary"] = {"showBand": True, "showMode": True}
    # Public projection: NEVER mirror auth credentials nor decoder runtime
    # plumbing (direwolf address, lora address, etc.) to the public
    # dashboard.  The dashboard only renders station + modes + summary +
    # user-visible names.
    settings.pop("auth", None)
    settings.pop("aprs", None)
    settings.pop("lora_aprs", None)
    settings.pop("asr", None)
    settings.pop("device_config", None)
    settings.pop("audio_config", None)
    return settings


def _resolve_qth():
    """Same logic as map_ionospheric / map_contacts."""
    from ..dependencies import state
    from ..dependencies.helpers import callsign_to_dxcc, maidenhead_to_latlon

    settings = state.db.get_settings()
    station = settings.get("station") or {}
    locator = str(station.get("locator") or "").strip().upper()
    station_callsign = str(station.get("callsign") or "").strip().upper()
    lat = lon = None
    if locator:
        pos = maidenhead_to_latlon(locator)
        if pos:
            lat, lon = pos
    if lat is None and station_callsign:
        dxcc = callsign_to_dxcc(station_callsign)
        if dxcc:
            lat = dxcc.get("lat")
            lon = dxcc.get("lon")
    if lat is None or lon is None:
        lat, lon = 39.5, -8.0
    return station_callsign, locator, float(lat), float(lon)


def _snapshot_map_ionospheric() -> Dict[str, Any]:
    from ..core.ionospheric import ionospheric_cache

    _, _, lat, lon = _resolve_qth()
    return ionospheric_cache.get_summary(latitude=lat, longitude=lon)


def _snapshot_map_contacts() -> Dict[str, Any]:
    """Same body as backend.app.api.map.map_contacts() with default params."""
    from datetime import timedelta

    from ..dependencies import state
    from ..dependencies.helpers import (
        callsign_to_dxcc,
        haversine_km,
    )

    window_minutes = 60
    limit = 2000

    station_callsign, locator, station_lat, station_lon = _resolve_qth()

    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=window_minutes)
    rows = state.db.get_callsign_events(
        limit=limit,
        start=start.isoformat(),
        end=now.isoformat(),
    )

    seen: Dict[str, dict] = {}
    for row in rows:
        cs = str(row.get("callsign") or "").strip().upper()
        if not cs:
            continue
        if str(row.get("mode") or "").upper() == "APRS":
            continue
        dxcc = callsign_to_dxcc(cs)
        if not dxcc:
            continue
        dest_lat = dxcc.get("lat")
        dest_lon = dxcc.get("lon")
        if dest_lat is None or dest_lon is None:
            continue
        snr = row.get("snr_db")
        band = str(row.get("band") or "")
        mode = str(row.get("mode") or "")
        ts = str(row.get("timestamp") or "")
        distance_km = haversine_km(station_lat, station_lon, dest_lat, dest_lon)
        key = f"{cs}|{band}"
        existing = seen.get(key)
        if existing is None or (
            snr is not None
            and (existing["snr_db"] is None or snr > existing["snr_db"])
        ):
            seen[key] = {
                "callsign": cs,
                "lat": dest_lat,
                "lon": dest_lon,
                "country": dxcc.get("country", ""),
                "continent": dxcc.get("continent", ""),
                "cq_zone": dxcc.get("cq_zone"),
                "band": band,
                "mode": mode,
                "snr_db": snr,
                "distance_km": distance_km,
                "timestamp": ts,
            }
    contacts = sorted(seen.values(), key=lambda x: x.get("timestamp") or "", reverse=True)
    return {
        "status": "ok",
        "window_minutes": window_minutes,
        "station": {
            "callsign": station_callsign,
            "locator": locator,
            "lat": station_lat,
            "lon": station_lon,
        },
        "contact_count": len(contacts),
        "contacts": contacts,
    }


def _build_academic_window(
    *, window: timedelta, bucket: str, raw_cap: int
) -> Dict[str, Any]:
    """Invoke the live academic_analytics() for a specific rolling window.

    Re-uses the heavy aggregation code path verbatim by calling the route
    function with stub Request and bypassed auth dep.  This guarantees the
    snapshot is byte-equivalent to what the live endpoint would return for
    the requested ``[now-window, now]`` query.

    The embedded ``raw_events`` list is capped to ``raw_cap`` to keep the
    overall push payload under shared-hosting POST limits.
    """
    from types import SimpleNamespace

    from ..api.analytics import academic_analytics
    from ..version import APP_VERSION

    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - window
    fake_request = SimpleNamespace(app=SimpleNamespace(version=APP_VERSION))
    result = academic_analytics(
        request=fake_request,  # type: ignore[arg-type]
        start=start_dt.isoformat(),
        end=end_dt.isoformat(),
        band=None,
        mode=None,
        bucket=bucket,
        _=False,
    )
    data = result.get("data") or {}
    raw = data.get("raw_events")
    if isinstance(raw, list) and len(raw) > raw_cap:
        raw_sorted = sorted(
            raw,
            key=lambda r: str(r.get("timestamp") or ""),
            reverse=True,
        )
        data["raw_events"] = raw_sorted[:raw_cap]
        data["raw_events_truncated"] = True
        data["raw_events_total"] = len(raw)
    return result


def _snapshot_analytics_academic() -> Dict[str, Any]:
    """Default 7-day / hour snapshot (back-compat for old PHP shim).

    Capped tighter than the per-window builders so we don't ship the same
    raw events twice in a single push (the per-window 7d builder already
    contains them).
    """
    return _build_academic_window(
        window=timedelta(days=7), bucket="hour", raw_cap=200
    )


def _snapshot_analytics_academic_1h() -> Dict[str, Any]:
    return _build_academic_window(
        window=timedelta(hours=1), bucket="minute", raw_cap=RAW_EVENTS_CAP
    )


def _snapshot_analytics_academic_24h() -> Dict[str, Any]:
    return _build_academic_window(
        window=timedelta(hours=24), bucket="hour", raw_cap=800
    )


def _snapshot_analytics_academic_7d() -> Dict[str, Any]:
    return _build_academic_window(
        window=timedelta(days=7), bucket="hour", raw_cap=500
    )


def _snapshot_analytics_academic_30d() -> Dict[str, Any]:
    # 30d uses ``day`` bucket so the series stays small; raw events are
    # heavily capped because this view is only used for the long-term
    # macro chart and we must keep the push payload under the receiver's
    # PHP ``post_max_size``.
    return _build_academic_window(
        window=timedelta(days=30), bucket="day", raw_cap=300
    )


# Hard cap on raw_events embedded in the analytics snapshot.  Keeps push
# payload size under shared-hosting POST limits (default 8 MB) even with
# week-long busy periods.  The dashboard renders a sliding view, so older
# rows past this cap are not visible anyway.
RAW_EVENTS_CAP = 1500


# ── Beacon snapshots ───────────────────────────────────────────────────────────

def _snapshot_beacon_status() -> Dict[str, Any]:
    """Mirrors GET /api/beacons/status — scheduler snapshot + catalog summary."""
    from ..dependencies import state
    from ..beacons.catalog import BANDS, BEACONS

    sched = getattr(state, "beacon_scheduler", None)
    snapshot = sched.snapshot() if sched is not None else {"running": False}
    return {
        "scheduler": snapshot,
        "catalog": {
            "beacons": len(BEACONS),
            "bands": len(BANDS),
            "active_beacons": sum(1 for b in BEACONS if b.status == "active"),
        },
        "time_sync": None,
    }


def _snapshot_beacon_analytics_overview() -> Dict[str, Any]:
    """Mirrors GET /api/beacons/analytics/overview with default 12 h / 3 h windows."""
    from ..dependencies import state
    from ..beacons.catalog import BANDS, BEACONS
    from ..beacons.propagation import build_beacon_propagation_summary
    from ..beacons.public_payloads import public_beacon_heatmap_cell
    from ..core.ionospheric import ionospheric_cache
    from ..api.beacons import (
        _build_kpis,
        _build_recent_activity_summary,
        _build_beacon_reading,
        _build_beacon_nowcast,
    )

    heatmap_hours = 12.0
    propagation_window_minutes = 180
    forecast_window_minutes = 180

    _, _, station_lat, station_lon = _resolve_qth()

    heatmap_rows = state.db.get_beacon_heatmap(hours=heatmap_hours)
    propagation_rows = state.db.get_beacon_observations(
        limit=10000,
        hours=max(0.1, propagation_window_minutes / 60.0),
        detected_only=False,
    )
    propagation = build_beacon_propagation_summary(propagation_rows, propagation_window_minutes)
    ionospheric = ionospheric_cache.get_summary(latitude=station_lat, longitude=station_lon)
    reading = _build_beacon_reading(propagation, ionospheric)
    forecast = _build_beacon_nowcast(propagation, ionospheric, forecast_window_minutes)

    now_iso = _now_iso()
    return {
        "status": "ok",
        "kind": "beacon_analytics",
        "source_kind": "snapshot",
        "generated_at_utc": now_iso,
        "snapshot_captured_at_utc": now_iso,
        "staleness_seconds": 0,
        "windows": {
            "heatmap_hours": heatmap_hours,
            "propagation_window_minutes": propagation_window_minutes,
            "forecast_window_minutes": forecast_window_minutes,
        },
        "freshness": {
            "label": "snapshot",
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


def _snapshot_beacon_observations() -> Dict[str, Any]:
    """Mirrors GET /api/beacons/observations with a 12-hour window, cap 200."""
    from ..dependencies import state
    from ..beacons.public_payloads import public_beacon_observation

    rows = state.db.get_beacon_observations(limit=200, hours=12.0, detected_only=False)
    public_rows = [
        row for row in (public_beacon_observation(r) for r in rows) if row is not None
    ]
    return {"observations": public_rows, "count": len(public_rows), "offset": 0}


def build_snapshot_bundle() -> Dict[str, Dict[str, Any]]:
    """Produce a dict ``{endpoint_key: {ts, payload}}`` for every endpoint.

    Failed snapshots are simply omitted; the receiver keeps serving the
    previous successful snapshot for that endpoint.
    """
    bundle: Dict[str, Dict[str, Any]] = {}
    builders = (
        (ENDPOINT_VERSION, _snapshot_version),
        (ENDPOINT_SCAN_STATUS, _snapshot_scan_status),
        (ENDPOINT_SETTINGS, _snapshot_settings),
        (ENDPOINT_MAP_IONOSPHERIC, _snapshot_map_ionospheric),
        # NOTE: map/contacts and analytics/academic* are NOT pre-computed
        # anymore. The receiver PHP shims now query mirror_callsign_events
        # directly so the dashboard period selector returns real-time
        # results. This keeps the per-push payload tiny (only kbytes of
        # version/scan/settings/ionospheric snapshots + delta events).
        # Beacon data lives in a separate local table (beacon_observations)
        # that is NOT mirrored row-by-row, so these three are snapshots.
        (ENDPOINT_BEACON_STATUS, _snapshot_beacon_status),
        (ENDPOINT_BEACON_ANALYTICS_OVERVIEW, _snapshot_beacon_analytics_overview),
        (ENDPOINT_BEACON_OBSERVATIONS, _snapshot_beacon_observations),
    )
    captured_at = _now_iso()
    for key, fn in builders:
        result = _safe(key, fn)
        if result is None:
            continue
        bundle[key] = {"captured_at": captured_at, "payload": result}
    return bundle


__all__ = [
    "ENDPOINT_VERSION",
    "ENDPOINT_SCAN_STATUS",
    "ENDPOINT_SETTINGS",
    "ENDPOINT_MAP_IONOSPHERIC",
    "ENDPOINT_MAP_CONTACTS",
    "ENDPOINT_ANALYTICS_ACADEMIC",
    "ENDPOINT_ANALYTICS_ACADEMIC_1H",
    "ENDPOINT_ANALYTICS_ACADEMIC_24H",
    "ENDPOINT_ANALYTICS_ACADEMIC_7D",
    "ENDPOINT_ANALYTICS_ACADEMIC_30D",
    "ENDPOINT_BEACON_STATUS",
    "ENDPOINT_BEACON_ANALYTICS_OVERVIEW",
    "ENDPOINT_BEACON_OBSERVATIONS",
    "build_snapshot_bundle",
]
