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
from math import ceil, log1p
from statistics import median, pstdev
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request

from app.dependencies import state
from app.dependencies.auth import optional_verify_basic_auth
from app.dependencies.helpers import (
    clamp, parse_event_timestamp, safe_float, sanitize_events_for_api,
    _mode_category, _normalise_snr,
    callsign_to_dxcc, maidenhead_to_latlon,
)
from app.decoders.ingest import is_valid_callsign


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
    if bucket == "minute":
        return ts.replace(second=0, microsecond=0)
    return ts.replace(minute=0, second=0, microsecond=0)


def _propagation_state(score: float) -> str:
    if score >= 70:
        return "Excellent"
    if score >= 50:
        return "Good"
    if score >= 30:
        return "Fair"
    return "Poor"


def _compute_category_score(cat_data: Dict) -> float:
    """
    Compute propagation score for a single mode category using the 3-formula
    approach.  Returns score in [0, 100].

    cat_data must contain aggregated metrics produced by the main loop.
    """
    category = cat_data["category"]
    n = cat_data["total_events"]
    if n <= 0:
        return 0.0

    snr_list = cat_data["snr_values"]
    pwr_list = cat_data["power_values"]
    avg_recency = cat_data["recency_sum"] / n
    avg_conf = cat_data["confidence_sum"] / n

    if category == "digital":
        decode_rate = cat_data["callsign_events"] / n if n > 0 else 0.0
        snr_c = _normalise_snr(median(snr_list), cat_data["dominant_mode"]) if snr_list else 0.0
        call_norm = clamp(log1p(cat_data["unique_callsigns"]) / log1p(20), 0.0, 1.0)
        return clamp(100.0 * (
            0.40 * decode_rate +
            0.35 * snr_c +
            0.15 * call_norm +
            0.10 * avg_recency
        ), 0.0, 100.0)

    if category == "cw":
        traffic_norm = clamp(log1p(n) / log1p(100), 0.0, 1.0)
        snr_c = _normalise_snr(median(snr_list), "CW") if snr_list else 0.0
        sig_c = clamp((median(pwr_list) + 120.0) / 70.0, 0.0, 1.0) if pwr_list else 0.3
        call_bonus = min(1.0, cat_data["callsign_events"] / max(1, n) * 3.0)
        score = 100.0 * (
            0.30 * traffic_norm +
            0.30 * snr_c +
            0.15 * sig_c +
            0.15 * call_bonus +
            0.10 * avg_recency
        )
        # Verification: occupancy-only events lack callsign confirmation
        if n > 5:
            conf_ratio = cat_data["callsign_events"] / n
            if conf_ratio < 0.03:
                verification = 0.65 + 0.35 * (conf_ratio / 0.03)
                score = score * verification
        return clamp(score, 0.0, 100.0)

    # SSB
    traffic_norm = clamp(log1p(n) / log1p(100), 0.0, 1.0)
    snr_c = _normalise_snr(median(snr_list), "SSB") if snr_list else 0.0
    sig_c = clamp((median(pwr_list) + 120.0) / 70.0, 0.0, 1.0) if pwr_list else 0.3
    transcript_bonus = 1.0 if cat_data.get("has_transcript") else 0.0
    call_bonus = min(1.0, cat_data["callsign_events"] / max(1, n) * 3.0)
    score = 100.0 * (
        0.20 * traffic_norm +
        0.25 * snr_c +
        0.15 * sig_c +
        0.20 * avg_conf +
        0.10 * transcript_bonus +
        0.05 * call_bonus +
        0.05 * avg_recency
    )
    # Verification: occupancy-only events lack callsign confirmation
    if n > 5:
        conf_ratio = cat_data["callsign_events"] / n
        if conf_ratio < 0.03:
            verification = 0.65 + 0.35 * (conf_ratio / 0.03)
            score = score * verification
    return clamp(score, 0.0, 100.0)


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
    if bucket_name not in {"minute", "hour", "day"}:
        raise HTTPException(status_code=400, detail="bucket must be 'minute', 'hour' or 'day'")

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

    # Pre-scan: determine which (band, mode) pairs had a real decoder running.
    # A pair is "confirmed" if it has ANY entries in callsign_events for that
    # specific band — even with empty callsigns — because those records are
    # only created by actual decoders (SSB ASR, CW detector, FT8 decoder).
    # Occupancy events for (band, mode) pairs without decoder activity come
    # purely from the DSP bandwidth heuristic and are excluded.
    # This is per-band so that e.g. SSB scan on 15m doesn't "confirm"
    # SSB occupancy on 12m where no SSB scan ever ran.
    confirmed_band_modes: Optional[set] = set()  # set of (band, mode) tuples
    try:
        with state.db._lock:
            rows = state.db.conn.execute(
                "SELECT DISTINCT UPPER(band), UPPER(mode) FROM callsign_events"
                " WHERE timestamp BETWEEN ? AND ?",
                (start_dt.isoformat(), end_dt.isoformat()),
            ).fetchall()
        for band_val, mode_val in rows:
            cs_band = band_val.strip()
            cs_mode = mode_val.strip()
            if cs_mode == "SSB_TRAFFIC":
                cs_mode = "SSB"
            elif cs_mode in ("CW_CANDIDATE", "CW_TRAFFIC"):
                cs_mode = "CW"
            confirmed_band_modes.add((cs_band, cs_mode))
    except Exception:
        # On any DB error, fall back to showing all modes
        confirmed_band_modes = None

    # Digital decoder modes have their mode label set by the active decoder
    # config, not the DSP bandwidth heuristic, so they are inherently
    # decoder-confirmed even when 0 callsigns are decoded in a window.
    _DECODER_CONFIRMED_MODES = frozenset({"FT8", "FT4", "WSPR"})

    series_map: Dict[Tuple[str, str, str], Dict] = {}
    callsign_map: Dict[Tuple[str, str, str, str], Dict] = {}
    timeline_totals: Dict[str, int] = {}
    raw_events: list = []

    propagation_by_band: Dict[str, Dict[str, Dict]] = {}  # band -> category -> agg
    propagation_trend: Dict[str, Dict[str, Dict]] = {}  # bucket_iso -> category -> agg

    total_events = 0
    snr_weighted_sum = 0.0
    snr_weight_total = 0
    snr_digital_sum = 0.0
    snr_digital_count = 0
    snr_analog_sum = 0.0
    snr_analog_count = 0
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

        # Normalize sub-modes so SSB_TRAFFIC counts as SSB and
        # CW_CANDIDATE / CW_TRAFFIC count as CW in all analytics aggregations.
        if mode_name == "SSB_TRAFFIC":
            mode_name = "SSB"
        elif mode_name in ("CW_CANDIDATE", "CW_TRAFFIC"):
            mode_name = "CW"

        event_type = str(event.get("type") or "").strip().lower()

        # Skip events for (band, mode) pairs without decoder activity.
        # Occupancy events are purely from the DSP bandwidth heuristic;
        # callsign events with empty callsign are voice-detection markers
        # that also lack decoder confirmation.
        # Exception: digital decoder modes are always allowed through
        # (see _DECODER_CONFIRMED_MODES above).
        if (
            confirmed_band_modes is not None
            and mode_name not in _DECODER_CONFIRMED_MODES
            and (band_name.upper(), mode_name) not in confirmed_band_modes
        ):
            if event_type == "occupancy":
                continue
            if event_type == "callsign":
                cs = str(event.get("callsign") or "").strip()
                if not cs or not is_valid_callsign(cs):
                    continue

        bucket_dt = _bucket_start(ts, bucket_name)
        bucket_iso = bucket_dt.isoformat()

        total_events += 1
        buckets_seen.add(bucket_iso)
        timeline_totals[bucket_iso] = timeline_totals.get(bucket_iso, 0) + 1

        snr_db = safe_float(event.get("snr_db"), default=None)
        if snr_db is not None:
            snr_weighted_sum += snr_db
            snr_weight_total += 1
            if _mode_category(mode_name) == "digital":
                snr_digital_sum += snr_db
                snr_digital_count += 1
            else:
                snr_analog_sum += snr_db
                snr_analog_count += 1

        # Collect individual event for raw export
        power_dbm = safe_float(event.get("power_dbm"), default=None)
        confidence_val = safe_float(event.get("confidence"), default=None)
        raw_ev = {
            "timestamp": ts.isoformat(),
            "type": event_type,
            "band": band_name,
            "mode": mode_name,
            "snr_db": round(snr_db, 1) if snr_db is not None else None,
            "frequency_hz": int(event.get("frequency_hz") or 0) or None,
            "power_dbm": round(power_dbm, 1) if power_dbm is not None else None,
            "confidence": round(confidence_val, 3) if confidence_val is not None else None,
        }
        if event_type == "callsign":
            cs_val = str(event.get("callsign") or "").strip().upper() or None
            grid_val = str(event.get("grid") or "").strip().upper() or None
            raw_ev["callsign"] = cs_val
            raw_ev["grid"] = grid_val
            crest = safe_float(event.get("crest_db"), default=None)
            raw_ev["crest_db"] = round(crest, 1) if crest is not None else None
            df = event.get("df_hz")
            raw_ev["df_hz"] = int(df) if df is not None else None
            raw_ev["source"] = str(event.get("source") or "").strip() or None
            # rf_gated: True when the inner station did NOT actually transmit
            # on RF on this leg (3rd-party encapsulation or TCPIP path token).
            # Stored as 0/1/NULL in DB; expose as bool/None for the frontend.
            rf_gated_val = event.get("rf_gated")
            raw_ev["rf_gated"] = bool(rf_gated_val) if rf_gated_val is not None else None
            # DXCC enrichment
            dxcc = callsign_to_dxcc(cs_val) if cs_val else None
            raw_ev["country"] = dxcc.get("country") if dxcc else None
            raw_ev["continent"] = dxcc.get("continent") if dxcc else None
            raw_ev["cq_zone"] = dxcc.get("cq_zone") if dxcc else None
            raw_ev["itu_zone"] = dxcc.get("itu_zone") if dxcc else None
            # Coordinates: grid locator > DXCC centroid
            coords = maidenhead_to_latlon(grid_val) if grid_val else None
            if coords:
                raw_ev["lat"] = coords[0]
                raw_ev["lon"] = coords[1]
                raw_ev["coord_source"] = "grid"
            elif dxcc and dxcc.get("lat") is not None:
                raw_ev["lat"] = dxcc["lat"]
                raw_ev["lon"] = dxcc["lon"]
                raw_ev["coord_source"] = "dxcc"
            else:
                raw_ev["lat"] = None
                raw_ev["lon"] = None
                raw_ev["coord_source"] = None
        raw_events.append(raw_ev)

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
            if callsign and is_valid_callsign(callsign):
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

        # ── Propagation: aggregate per band × category ────────────
        mode_raw = str(event.get("mode") or "").strip().upper()
        cat = _mode_category(mode_raw or mode_name)

        def _ensure_cat(container, key, category):
            cats = container.setdefault(key, {})
            if category not in cats:
                cats[category] = {
                    "category": category,
                    "total_events": 0,
                    "callsign_events": 0,
                    "unique_callsigns": 0,
                    "snr_values": [],
                    "power_values": [],
                    "recency_sum": 0.0,
                    "confidence_sum": 0.0,
                    "has_transcript": False,
                    "dominant_mode": mode_raw or mode_name,
                    "_callsign_set": set(),
                    "_mode_counts": {},
                }
            return cats[category]

        band_cat = _ensure_cat(propagation_by_band, band_name, cat)
        trend_cat = _ensure_cat(propagation_trend, bucket_iso, cat)

        for agg in (band_cat, trend_cat):
            agg["total_events"] += 1
            agg["_mode_counts"][mode_raw or mode_name] = agg["_mode_counts"].get(mode_raw or mode_name, 0) + 1

            if event_type == "callsign":
                agg["callsign_events"] += 1
                cs = str(event.get("callsign") or "").strip().upper()
                if cs:
                    agg["_callsign_set"].add(cs)

            if snr_db is not None:
                agg["snr_values"].append(snr_db)

            pwr = safe_float(event.get("power_dbm"), default=None)
            if pwr is not None:
                agg["power_values"].append(pwr)

            age_min = max(0.0, (end_dt - ts).total_seconds() / 60.0)
            recency = clamp(1.0 - (age_min / max(1.0, period_minutes)), 0.2, 1.0)
            agg["recency_sum"] += recency

            conf = safe_float(event.get("confidence"), default=None)
            if conf is not None:
                agg["confidence_sum"] += clamp(conf, 0.0, 1.0)

            if not agg["has_transcript"]:
                raw_text = event.get("raw") or event.get("msg") or ""
                if isinstance(raw_text, str) and len(raw_text.strip()) > 2:
                    agg["has_transcript"] = True

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
                "snr_count": int(row["snr_count"]),
            }
        )

    series_rows.sort(key=lambda item: (item["ts"], item["band"], item["mode"]))

    callsign_rows = list(callsign_map.values())
    callsign_rows.sort(key=lambda item: (item["ts"], item["band"], item["mode"], item["callsign"]))

    # ── Finalise propagation category aggregates ───────────────────
    def _finalise_cats(container):
        for key, cats in container.items():
            for agg in cats.values():
                n = agg["total_events"]
                if n > 0:
                    agg["unique_callsigns"] = len(agg["_callsign_set"])
                    if agg["_mode_counts"]:
                        agg["dominant_mode"] = max(agg["_mode_counts"], key=agg["_mode_counts"].get)
                del agg["_callsign_set"]
                del agg["_mode_counts"]

    _finalise_cats(propagation_by_band)
    _finalise_cats(propagation_trend)

    propagation_band_rows = []
    for band_name_key, cats in propagation_by_band.items():
        cat_scores = []
        cat_weights = []
        total_ev = 0
        for agg in cats.values():
            if agg["total_events"] > 0:
                sc = _compute_category_score(agg)
                cat_scores.append(sc)
                cat_weights.append(agg["total_events"])
                total_ev += agg["total_events"]
        total_w = sum(cat_weights)
        score = sum(s * w for s, w in zip(cat_scores, cat_weights)) / total_w if total_w > 0 else 0.0
        propagation_band_rows.append(
            {
                "band": band_name_key,
                "events": int(total_ev),
                "score": round(score, 3),
                "state": _propagation_state(score),
            }
        )

    propagation_band_rows.sort(key=lambda item: (item["score"], item["events"]), reverse=True)

    trend_rows = []
    for bucket_key, cats in propagation_trend.items():
        cat_scores = []
        cat_weights = []
        for agg in cats.values():
            if agg["total_events"] > 0:
                sc = _compute_category_score(agg)
                cat_scores.append(sc)
                cat_weights.append(agg["total_events"])
        total_w = sum(cat_weights)
        score = sum(s * w for s, w in zip(cat_scores, cat_weights)) / total_w if total_w > 0 else 0.0
        trend_rows.append(
            {
                "ts": bucket_key,
                "score": round(score, 3),
                "state": _propagation_state(score),
            }
        )
    trend_rows.sort(key=lambda item: item["ts"])

    timeline_rows = [
        {"ts": ts, "count": int(count)} for ts, count in sorted(timeline_totals.items(), key=lambda item: item[0])
    ]

    bucket_seconds = 60 if bucket_name == "minute" else (3600 if bucket_name == "hour" else 86400)
    expected_buckets = max(1, int(ceil((end_dt - start_dt).total_seconds() / bucket_seconds)))
    coverage_pct = clamp((len(buckets_seen) / expected_buckets) * 100.0, 0.0, 100.0)

    snr_avg = (snr_weighted_sum / snr_weight_total) if snr_weight_total > 0 else 0.0
    snr_avg_digital = (snr_digital_sum / snr_digital_count) if snr_digital_count > 0 else None
    snr_avg_analog = (snr_analog_sum / snr_analog_count) if snr_analog_count > 0 else None

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
            "snr_avg_digital": round(snr_avg_digital, 3) if snr_avg_digital is not None else None,
            "snr_avg_analog": round(snr_avg_analog, 3) if snr_avg_analog is not None else None,
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
            "raw_events": raw_events,
        },
    }
