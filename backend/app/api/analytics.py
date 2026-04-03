# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Academic analytics API endpoints

"""
Academic Analytics API
======================
Aggregated analytics endpoints for academic dashboards.
"""

from datetime import datetime, timedelta, timezone
from math import ceil
from statistics import pstdev
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request

from app.dependencies import state
from app.dependencies.auth import optional_verify_basic_auth
from app.dependencies.helpers import clamp, parse_event_timestamp, safe_float, sanitize_events_for_api


router = APIRouter()


def _parse_iso_utc(value: Optional[str], field_name: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name} timestamp") from exc


def _bucket_start(ts: datetime, bucket: str) -> datetime:
    if bucket == "day":
        return ts.replace(hour=0, minute=0, second=0, microsecond=0)
    return ts.replace(minute=0, second=0, microsecond=0)


def _propagation_state(score: float) -> str:
    if score >= 75:
        return "Excellent"
    if score >= 60:
        return "Good"
    if score >= 45:
        return "Fair"
    return "Poor"


def _compute_propagation_score(
    snr_db: Optional[float],
    confidence: Optional[float],
    event_type: str,
    ts: datetime,
    end_dt: datetime,
    period_minutes: float,
) -> Tuple[float, float]:
    base_weight = 1.0 if event_type == "callsign" else 0.55
    age_minutes = max(0.0, (end_dt - ts).total_seconds() / 60.0)
    recency_weight = clamp(1.0 - (age_minutes / max(1.0, period_minutes)), 0.2, 1.0)

    snr_norm = 0.5
    if snr_db is not None:
        snr_norm = clamp((snr_db + 20.0) / 40.0, 0.0, 1.0)

    default_confidence = 0.6 if event_type == "callsign" else 0.5
    conf_raw = safe_float(confidence, default=default_confidence)
    if conf_raw is None:
        conf_raw = default_confidence
    conf = clamp(conf_raw, 0.0, 1.0)

    combined_weight = base_weight * recency_weight
    return snr_norm * conf * combined_weight, combined_weight


@router.get("/analytics/academic")
def academic_analytics(
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    band: Optional[str] = None,
    mode: Optional[str] = None,
    bucket: str = "hour",
    _: bool = Depends(optional_verify_basic_auth),
) -> Dict:
    """
    Return aggregated analytics payload for academic dashboard visualizations.

    Output is lightweight and ready for chart rendering.
    """
    bucket_name = str(bucket or "hour").strip().lower()
    if bucket_name not in {"hour", "day"}:
        raise HTTPException(status_code=400, detail="bucket must be 'hour' or 'day'")

    end_dt = _parse_iso_utc(end, "end") or datetime.now(timezone.utc)
    start_dt = _parse_iso_utc(start, "start") or (end_dt - timedelta(days=7))
    if start_dt >= end_dt:
        raise HTTPException(status_code=400, detail="start must be earlier than end")

    db_events = state.db.get_events(
        limit=None,
        band=band,
        mode=mode,
        start=start_dt.isoformat(),
        end=end_dt.isoformat(),
    )
    events = sanitize_events_for_api(db_events)

    series_map: Dict[Tuple[str, str, str], Dict] = {}
    callsign_map: Dict[Tuple[str, str, str, str], Dict] = {}
    timeline_totals: Dict[str, int] = {}

    propagation_by_band: Dict[str, Dict] = {}
    propagation_trend: Dict[str, Dict] = {}

    total_events = 0
    snr_weighted_sum = 0.0
    snr_weight_total = 0
    unique_callsigns = set()
    buckets_seen = set()

    period_minutes = max(1.0, (end_dt - start_dt).total_seconds() / 60.0)

    for event in events:
        ts = parse_event_timestamp(str(event.get("timestamp") or ""))
        if ts is None:
            continue
        ts = ts.astimezone(timezone.utc)
        if ts < start_dt or ts > end_dt:
            continue

        band_name = str(event.get("band") or "").strip()
        mode_name = str(event.get("mode") or "").strip().upper()
        if not band_name or not mode_name:
            continue

        event_type = str(event.get("type") or "").strip().lower()
        bucket_dt = _bucket_start(ts, bucket_name)
        bucket_iso = bucket_dt.isoformat()

        total_events += 1
        buckets_seen.add(bucket_iso)
        timeline_totals[bucket_iso] = timeline_totals.get(bucket_iso, 0) + 1

        snr_db = safe_float(event.get("snr_db"), default=None)
        if snr_db is not None:
            snr_weighted_sum += snr_db
            snr_weight_total += 1

        series_key = (bucket_iso, band_name, mode_name)
        bucket_obj = series_map.get(series_key)
        if bucket_obj is None:
            bucket_obj = {
                "ts": bucket_iso,
                "band": band_name,
                "mode": mode_name,
                "count": 0,
                "snr_sum": 0.0,
                "snr_count": 0,
            }
            series_map[series_key] = bucket_obj

        bucket_obj["count"] += 1
        if snr_db is not None:
            bucket_obj["snr_sum"] += snr_db
            bucket_obj["snr_count"] += 1

        if event_type == "callsign":
            callsign = str(event.get("callsign") or "").strip().upper()
            if callsign:
                unique_callsigns.add(callsign)
                call_key = (bucket_iso, band_name, mode_name, callsign)
                call_obj = callsign_map.get(call_key)
                if call_obj is None:
                    call_obj = {
                        "ts": bucket_iso,
                        "band": band_name,
                        "mode": mode_name,
                        "callsign": callsign,
                        "hits": 0,
                    }
                    callsign_map[call_key] = call_obj
                call_obj["hits"] += 1

        weighted_score, weighted_amount = _compute_propagation_score(
            snr_db=snr_db,
            confidence=safe_float(event.get("confidence"), default=None),
            event_type=event_type,
            ts=ts,
            end_dt=end_dt,
            period_minutes=period_minutes,
        )

        band_prop = propagation_by_band.get(band_name)
        if band_prop is None:
            band_prop = {
                "band": band_name,
                "events": 0,
                "weighted_score_sum": 0.0,
                "weighted_sum": 0.0,
            }
            propagation_by_band[band_name] = band_prop

        band_prop["events"] += 1
        band_prop["weighted_score_sum"] += weighted_score
        band_prop["weighted_sum"] += weighted_amount

        trend_prop = propagation_trend.get(bucket_iso)
        if trend_prop is None:
            trend_prop = {
                "ts": bucket_iso,
                "weighted_score_sum": 0.0,
                "weighted_sum": 0.0,
            }
            propagation_trend[bucket_iso] = trend_prop

        trend_prop["weighted_score_sum"] += weighted_score
        trend_prop["weighted_sum"] += weighted_amount

    series_rows = []
    for row in series_map.values():
        snr_avg = (row["snr_sum"] / row["snr_count"]) if row["snr_count"] > 0 else 0.0
        series_rows.append(
            {
                "ts": row["ts"],
                "band": row["band"],
                "mode": row["mode"],
                "count": int(row["count"]),
                "snr": round(float(snr_avg), 3),
            }
        )

    series_rows.sort(key=lambda item: (item["ts"], item["band"], item["mode"]))

    callsign_rows = list(callsign_map.values())
    callsign_rows.sort(key=lambda item: (item["ts"], item["band"], item["mode"], item["callsign"]))

    propagation_band_rows = []
    for row in propagation_by_band.values():
        denom = row["weighted_sum"]
        score = (row["weighted_score_sum"] / denom * 100.0) if denom > 0 else 0.0
        propagation_band_rows.append(
            {
                "band": row["band"],
                "events": int(row["events"]),
                "score": round(score, 3),
                "state": _propagation_state(score),
            }
        )

    propagation_band_rows.sort(key=lambda item: (item["score"], item["events"]), reverse=True)

    trend_rows = []
    for row in propagation_trend.values():
        denom = row["weighted_sum"]
        score = (row["weighted_score_sum"] / denom * 100.0) if denom > 0 else 0.0
        trend_rows.append(
            {
                "ts": row["ts"],
                "score": round(score, 3),
                "state": _propagation_state(score),
            }
        )
    trend_rows.sort(key=lambda item: item["ts"])

    timeline_rows = [
        {"ts": ts, "count": int(count)} for ts, count in sorted(timeline_totals.items(), key=lambda item: item[0])
    ]

    bucket_seconds = 3600 if bucket_name == "hour" else 86400
    expected_buckets = max(1, int(ceil((end_dt - start_dt).total_seconds() / bucket_seconds)))
    coverage_pct = clamp((len(buckets_seen) / expected_buckets) * 100.0, 0.0, 100.0)

    snr_avg = (snr_weighted_sum / snr_weight_total) if snr_weight_total > 0 else 0.0

    overall_prop = 0.0
    if propagation_band_rows:
        weighted_score_sum = 0.0
        weighted_events = 0
        for row in propagation_band_rows:
            weighted_score_sum += row["score"] * row["events"]
            weighted_events += row["events"]
        overall_prop = weighted_score_sum / weighted_events if weighted_events > 0 else 0.0

    best_band = propagation_band_rows[0] if propagation_band_rows else None
    trend_scores = [row["score"] for row in trend_rows]
    trend_std = pstdev(trend_scores) if len(trend_scores) > 1 else 0.0
    stability_pct = clamp(100.0 - trend_std * 2.5, 0.0, 100.0)

    return {
        "status": "ok",
        "app_version": str(getattr(request.app, "version", "")),
        "snapshot_utc": datetime.now(timezone.utc).isoformat(),
        "period": {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "bucket": bucket_name,
        },
        "filters": {
            "band": band,
            "mode": mode,
        },
        "kpis": {
            "total_events": int(total_events),
            "unique_callsigns": int(len(unique_callsigns)),
            "snr_avg": round(snr_avg, 3),
            "coverage_pct": round(coverage_pct, 3),
            "propagation_score": round(overall_prop, 3),
            "propagation_state": _propagation_state(overall_prop),
            "best_band": best_band,
            "stability_pct": round(stability_pct, 3),
        },
        "data": {
            "series": series_rows,
            "callsigns": callsign_rows,
            "timeline": timeline_rows,
            "propagation_by_band": propagation_band_rows,
            "propagation_trend": trend_rows,
        },
    }
