# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 18:20:00 UTC


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


_MODE_DIAL_FREQUENCIES = {
    "FT8": [
        1840000,
        3573000,
        5357000,
        7074000,
        10136000,
        14074000,
        18100000,
        21074000,
        24915000,
        28074000,
        50313000,
    ],
    "FT4": [
        3575000,
        7047500,
        10140000,
        14080000,
        18104000,
        21140000,
        24919000,
        28180000,
    ],
}


def _iter_peak_candidates(snapshot):
    peaks = snapshot.get("peaks") or []
    if peaks:
        for item in peaks:
            if not isinstance(item, dict):
                continue
            offset_hz = _safe_float(item.get("offset_hz"), default=0.0)
            level_db = _safe_float(item.get("db"), default=-160.0)
            yield {
                "offset_hz": offset_hz,
                "level_db": level_db,
            }
        return

    fft_db = snapshot.get("fft_db") or []
    bin_hz = _safe_float(snapshot.get("bin_hz"), default=0.0)
    if not fft_db or bin_hz <= 0:
        return
    size = len(fft_db)
    center_idx = size // 2
    for idx, raw in enumerate(fft_db):
        level_db = _safe_float(raw, default=-160.0)
        offset_hz = (idx - center_idx) * bin_hz
        yield {
            "offset_hz": float(offset_hz),
            "level_db": level_db,
        }


def _normalize_modes(modes):
    normalized = []
    for mode in list(modes or []):
        text = str(mode or "").strip().upper()
        if text in _MODE_DIAL_FREQUENCIES and text not in normalized:
            normalized.append(text)
    return normalized or ["FT8"]


def _nearest_mode_for_frequency(frequency_hz, enabled_modes, mode_hint_tolerance_hz=2500.0):
    best_mode = None
    best_delta = None
    for mode in enabled_modes:
        dial_list = _MODE_DIAL_FREQUENCIES.get(mode, [])
        for dial_hz in dial_list:
            delta = abs(float(frequency_hz) - float(dial_hz))
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_mode = mode

    if best_mode is None:
        return enabled_modes[0]
    if best_delta is None or best_delta > float(mode_hint_tolerance_hz):
        return enabled_modes[0]
    return best_mode


def detect_ft8_candidates(
    snapshot,
    min_snr_db=8.0,
    min_audio_hz=150.0,
    max_audio_hz=3200.0,
    max_candidates=8,
):
    return detect_ft_candidates(
        snapshot,
        min_snr_db=min_snr_db,
        min_audio_hz=min_audio_hz,
        max_audio_hz=max_audio_hz,
        max_candidates=max_candidates,
        modes=["FT8"],
    )


def detect_ft_candidates(
    snapshot,
    min_snr_db=8.0,
    min_audio_hz=150.0,
    max_audio_hz=3200.0,
    max_candidates=8,
    modes=None,
    mode_hint_tolerance_hz=2500.0,
):
    if not isinstance(snapshot, dict):
        return []

    center_hz = _safe_float(snapshot.get("center_hz"), default=0.0)
    if center_hz <= 0:
        return []

    enabled_modes = _normalize_modes(modes)

    noise_floor_db = _safe_float(snapshot.get("noise_floor_db"), default=-120.0)
    candidates = []
    for peak in _iter_peak_candidates(snapshot):
        offset_hz = abs(_safe_float(peak.get("offset_hz"), default=0.0))
        if offset_hz < float(min_audio_hz) or offset_hz > float(max_audio_hz):
            continue

        level_db = _safe_float(peak.get("level_db"), default=-160.0)
        snr_db = level_db - noise_floor_db
        if snr_db < float(min_snr_db):
            continue

        confidence = min(0.99, max(0.01, snr_db / 30.0))
        frequency_hz = _safe_int(round(center_hz + _safe_float(peak.get("offset_hz"), default=0.0)), default=0)
        mode = _nearest_mode_for_frequency(
            frequency_hz,
            enabled_modes,
            mode_hint_tolerance_hz=mode_hint_tolerance_hz,
        )

        candidates.append(
            {
                "mode": mode,
                "frequency_hz": frequency_hz,
                "offset_hz": _safe_float(peak.get("offset_hz"), default=0.0),
                "snr_db": round(snr_db, 2),
                "confidence": round(confidence, 3),
            }
        )

    candidates.sort(key=lambda item: (item.get("confidence", 0.0), item.get("snr_db", 0.0)), reverse=True)
    return candidates[: max(1, int(max_candidates))]
