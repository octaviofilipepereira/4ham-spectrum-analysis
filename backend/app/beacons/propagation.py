"""Beacon-specific propagation map and score helpers."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import median
from typing import Any, Mapping

from app.beacons.catalog import BANDS, BEACONS, Beacon
from app.dependencies.helpers import callsign_to_dxcc, haversine_km, maidenhead_to_latlon

_DEFAULT_STATION_LAT = 39.5
_DEFAULT_STATION_LON = -8.0


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _safe_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _parse_iso_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _score_to_state(score: float) -> str:
    if score >= 70.0:
        return "Excellent"
    if score >= 50.0:
        return "Good"
    if score >= 30.0:
        return "Fair"
    return "Poor"


def _normalise_beacon_snr(snr_db: float | None) -> float:
    if snr_db is None:
        return 0.0
    # Beacon copy starts to become meaningful once the 100 W dash rises above
    # the 3 dB detector floor. Map 3..21 dB to 0..1 and clamp everything else.
    return _clamp((snr_db - 3.0) / 18.0, 0.0, 1.0)


def _resolve_station(settings: Mapping[str, Any] | None) -> dict[str, Any]:
    station = (settings or {}).get("station") or {}
    locator = str(station.get("locator") or "").strip().upper()
    station_callsign = str(station.get("callsign") or "").strip().upper()

    station_lat: float | None = None
    station_lon: float | None = None
    if locator:
        coords = maidenhead_to_latlon(locator)
        if coords:
            station_lat, station_lon = coords

    if station_lat is None and station_callsign:
        dxcc = callsign_to_dxcc(station_callsign)
        if dxcc:
            station_lat = dxcc.get("lat")
            station_lon = dxcc.get("lon")

    if station_lat is None or station_lon is None:
        station_lat = _DEFAULT_STATION_LAT
        station_lon = _DEFAULT_STATION_LON

    return {
        "callsign": station_callsign,
        "locator": locator,
        "lat": station_lat,
        "lon": station_lon,
    }


def _beacon_from_row(row: Mapping[str, Any]) -> Beacon | None:
    callsign = str(row.get("beacon_callsign") or "").strip().upper()
    if callsign:
        beacon = next((item for item in BEACONS if item.callsign == callsign), None)
        if beacon is not None:
            return beacon
    beacon_index = row.get("beacon_index")
    if beacon_index is None:
        return None
    try:
        return BEACONS[int(beacon_index)]
    except (IndexError, TypeError, ValueError):
        return None


def _row_state(row: Mapping[str, Any]) -> str:
    if bool(row.get("detected")):
        return "detected"
    lead_snr = _safe_float(row.get("snr_db_100w"))
    if lead_snr is not None and lead_snr > 0.0:
        return "weak"
    return "nocopy"


def _recency_component(timestamp: datetime | None, now: datetime, window_minutes: int) -> float:
    if timestamp is None or window_minutes <= 0:
        return 0.0
    age_minutes = max(0.0, (now - timestamp).total_seconds() / 60.0)
    return _clamp(1.0 - (age_minutes / float(window_minutes)), 0.0, 1.0)


def build_beacon_map_contacts(
    rows: list[dict[str, Any]],
    settings: Mapping[str, Any] | None,
    window_minutes: int,
) -> dict[str, Any]:
    station = _resolve_station(settings)
    latest_by_callsign: dict[str, dict[str, Any]] = {}
    bands_by_callsign: dict[str, set[str]] = {}

    for row in rows:
        if not bool(row.get("detected")):
            continue
        beacon = _beacon_from_row(row)
        if beacon is None:
            continue
        slot_start = _parse_iso_timestamp(row.get("slot_start_utc"))
        if slot_start is None:
            continue
        band_name = str(row.get("band_name") or "").strip()

        # Agregar todas as bandas detectadas na janela
        if beacon.callsign not in bands_by_callsign:
            bands_by_callsign[beacon.callsign] = set()
        if band_name:
            bands_by_callsign[beacon.callsign].add(band_name)

        current = latest_by_callsign.get(beacon.callsign)
        if current is not None and slot_start <= current["_slot_start"]:
            continue

        latest_by_callsign[beacon.callsign] = {
            "callsign": beacon.callsign,
            "location": beacon.location,
            "lat": beacon.lat,
            "lon": beacon.lon,
            "band": band_name,
            "mode": "BEACON",
            "snr_db": _safe_float(row.get("snr_db_100w")),
            "dash_levels_detected": max(0, min(4, int(row.get("dash_levels_detected") or 0))),
            "timestamp": slot_start.isoformat(),
            "last_detection_utc": slot_start.isoformat(),
            "state": "Detected",
            "beacon_status": beacon.status,
            "distance_km": haversine_km(station["lat"], station["lon"], beacon.lat, beacon.lon),
            "_slot_start": slot_start,
        }

    contacts = sorted(latest_by_callsign.values(), key=lambda item: item["timestamp"], reverse=True)
    for item in contacts:
        item.pop("_slot_start", None)
        cs = item["callsign"]
        # Incluir lista ordenada de todas as bandas detectadas na janela
        item["bands"] = sorted(bands_by_callsign.get(cs, set()), key=lambda b: ["20m","17m","15m","12m","10m"].index(b) if b in ["20m","17m","15m","12m","10m"] else 99)

    return {
        "status": "ok",
        "kind": "beacon",
        "window_minutes": max(1, int(window_minutes or 60)),
        "station": station,
        "contact_count": len(contacts),
        "contacts": contacts,
    }


def build_beacon_propagation_summary(
    rows: list[dict[str, Any]],
    window_minutes: int,
) -> dict[str, Any]:
    safe_window_minutes = max(1, int(window_minutes or 60))
    now = datetime.now(timezone.utc)
    per_band: dict[str, list[dict[str, Any]]] = {band.name: [] for band in BANDS}
    for row in rows:
        band_name = str(row.get("band_name") or "").strip()
        if band_name in per_band:
            per_band[band_name].append(row)

    band_entries: list[dict[str, Any]] = []
    monitored_scores: list[float] = []
    total_slots_all = 0

    for band in BANDS:
        band_rows = per_band.get(band.name, [])
        total_slots = len(band_rows)
        total_slots_all += total_slots

        detected_rows = [row for row in band_rows if bool(row.get("detected"))]
        weak_rows = [row for row in band_rows if _row_state(row) == "weak"]
        detected_beacons = {str(row.get("beacon_callsign") or "").strip().upper() for row in detected_rows if row.get("beacon_callsign")}
        weak_beacons = {str(row.get("beacon_callsign") or "").strip().upper() for row in weak_rows if row.get("beacon_callsign")}

        detection_rate = (len(detected_rows) / total_slots) if total_slots else 0.0
        weak_rate = (len(weak_rows) / total_slots) if total_slots else 0.0

        snr_source = detected_rows or weak_rows
        snr_values = [value for value in (_safe_float(row.get("snr_db_100w")) for row in snr_source) if value is not None]
        max_snr = max(snr_values) if snr_values else None
        median_snr = median(snr_values) if snr_values else None

        dash_values = [
            max(0.0, min(4.0, float(row.get("dash_levels_detected") or 0.0)))
            for row in detected_rows
        ]
        median_dashes = median(dash_values) if dash_values else 0.0

        latest_detected = max(
            (_parse_iso_timestamp(row.get("slot_start_utc")) for row in detected_rows),
            default=None,
        )
        latest_meaningful = max(
            (_parse_iso_timestamp(row.get("slot_start_utc")) for row in (detected_rows or weak_rows)),
            default=None,
        )

        if total_slots > 0:
            trace_component = min(1.0, detection_rate + (0.35 * weak_rate))
            snr_component = _normalise_beacon_snr(median_snr)
            dash_component = _clamp(median_dashes / 4.0, 0.0, 1.0)
            recency_component = _recency_component(latest_meaningful, now, safe_window_minutes)
            band_score = 100.0 * (
                0.50 * trace_component +
                0.20 * snr_component +
                0.20 * dash_component +
                0.10 * recency_component
            )
            band_score = round(_clamp(band_score, 0.0, 100.0), 1)
            band_state = _score_to_state(band_score)
            monitored_scores.append(band_score)
        else:
            band_score = 0.0
            band_state = "No data"

        band_entries.append({
            "band": band.name,
            "score": band_score,
            "state": band_state,
            "events": total_slots,
            "max_snr_db": round(max_snr, 1) if max_snr is not None else None,
            "detected_beacons": len(detected_beacons),
            "weak_beacons": len(weak_beacons),
            "detection_rate": round(detection_rate, 3),
            "weak_rate": round(weak_rate, 3),
            "mode_category": "beacon",
            "latest_detected_utc": latest_detected.isoformat() if latest_detected else None,
        })

    if monitored_scores:
        overall_score = round(float(median(monitored_scores)), 1)
        overall_state = _score_to_state(overall_score)
    else:
        overall_score = 0.0
        overall_state = "No data"

    return {
        "status": "ok",
        "kind": "beacon",
        "window_minutes": safe_window_minutes,
        "event_count": total_slots_all,
        "overall": {
            "score": overall_score,
            "state": overall_state,
        },
        "bands": band_entries,
    }