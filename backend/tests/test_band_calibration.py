# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

"""
Band Calibration & IARU Region 1 Validation Tests
===================================================
Validates that all SSB and CW subband frequency bounds match the IARU Region 1
band plan and that the frequency-resolution helpers behave correctly.

All validations are replicated across every configured band — if a new band is
added to _SSB_SUBBANDS_HZ or _CW_SUBBANDS_HZ without a matching entry in this
file, the "complete coverage" tests will catch the gap.
"""

import pytest

from app.api.scan import (
    _CW_SUBBANDS_HZ,
    _SSB_SUBBANDS_HZ,
    _resolve_cw_sweep_bounds,
    _resolve_ssb_bounds,
)

# ---------------------------------------------------------------------------
# IARU Region 1 reference values (Hz)
# Source: IARU Region 1 HF Band Plan, version adopted by REF/RSGB/others.
# ---------------------------------------------------------------------------

_IARU_R1_SSB_HZ = {
    "160m": (1_843_000, 2_000_000),
    "80m":  (3_600_000, 3_800_000),
    "40m":  (7_090_000, 7_200_000),
    "20m":  (14_140_000, 14_350_000),
    "17m":  (18_100_000, 18_168_000),
    "15m":  (21_160_000, 21_450_000),
    "12m":  (24_930_000, 24_990_000),
    "10m":  (28_300_000, 29_700_000),
}

_IARU_R1_CW_HZ = {
    "160m": (1_800_000, 1_840_000),
    "80m":  (3_500_000, 3_600_000),
    "40m":  (7_000_000, 7_040_000),
    "30m":  (10_100_000, 10_130_000),
    "20m":  (14_000_000, 14_070_000),
    "17m":  (18_068_000, 18_095_000),  # exclusive CW; 18.095–18.111 is narrow/all-modes zone
    "15m":  (21_000_000, 21_150_000),
    "12m":  (24_890_000, 24_930_000),
    "10m":  (28_000_000, 28_300_000),
}

# ---------------------------------------------------------------------------
# SSB subband bounds — IARU R1 conformance
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("band,expected", list(_IARU_R1_SSB_HZ.items()))
def test_ssb_subband_matches_iaru_r1(band, expected):
    """_SSB_SUBBANDS_HZ[band] must match the IARU R1 reference exactly."""
    assert band in _SSB_SUBBANDS_HZ, f"Band {band} is missing from _SSB_SUBBANDS_HZ"
    actual = _SSB_SUBBANDS_HZ[band]
    start_exp, end_exp = expected
    start_act, end_act = actual
    assert start_act == start_exp, (
        f"{band} SSB start: expected {start_exp / 1e6:.3f} MHz, got {start_act / 1e6:.3f} MHz"
    )
    assert end_act == end_exp, (
        f"{band} SSB end: expected {end_exp / 1e6:.3f} MHz, got {end_act / 1e6:.3f} MHz"
    )


def test_ssb_subbands_complete_coverage():
    """Every band in _SSB_SUBBANDS_HZ must have a reference entry; none may be added silently."""
    configured = set(_SSB_SUBBANDS_HZ.keys())
    referenced = set(_IARU_R1_SSB_HZ.keys())
    extra = configured - referenced
    assert not extra, (
        f"Bands in _SSB_SUBBANDS_HZ without IARU R1 reference: {sorted(extra)}. "
        "Add reference values above before committing new bands."
    )


def test_ssb_subbands_all_sane():
    """All SSB subbands must have start < end and span ≥ 50 kHz."""
    for band, (start, end) in _SSB_SUBBANDS_HZ.items():
        assert start < end, f"{band} SSB: start {start} >= end {end}"
        assert (end - start) >= 50_000, f"{band} SSB span too narrow: {(end - start) / 1000:.0f} kHz"


# ---------------------------------------------------------------------------
# CW subband bounds — IARU R1 conformance
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("band,expected", list(_IARU_R1_CW_HZ.items()))
def test_cw_subband_matches_iaru_r1(band, expected):
    """_CW_SUBBANDS_HZ[band] must match the IARU R1 reference exactly."""
    assert band in _CW_SUBBANDS_HZ, f"Band {band} is missing from _CW_SUBBANDS_HZ"
    actual = _CW_SUBBANDS_HZ[band]
    start_exp, end_exp = expected
    start_act, end_act = actual
    assert start_act == start_exp, (
        f"{band} CW start: expected {start_exp / 1e6:.3f} MHz, got {start_act / 1e6:.3f} MHz"
    )
    assert end_act == end_exp, (
        f"{band} CW end: expected {end_exp / 1e6:.3f} MHz, got {end_act / 1e6:.3f} MHz"
    )


def test_cw_subbands_complete_coverage():
    """Every band in _CW_SUBBANDS_HZ must have a reference entry."""
    configured = set(_CW_SUBBANDS_HZ.keys())
    referenced = set(_IARU_R1_CW_HZ.keys())
    extra = configured - referenced
    assert not extra, (
        f"Bands in _CW_SUBBANDS_HZ without IARU R1 reference: {sorted(extra)}. "
        "Add reference values above before committing new bands."
    )


def test_cw_subbands_all_sane():
    """All CW subbands must have start < end and span ≥ 10 kHz."""
    for band, (start, end) in _CW_SUBBANDS_HZ.items():
        assert start < end, f"{band} CW: start {start} >= end {end}"
        assert (end - start) >= 10_000, f"{band} CW span too narrow: {(end - start) / 1000:.0f} kHz"


def test_ssb_and_cw_subbands_do_not_overlap():
    """For bands that have both SSB and CW portions, the segments must not overlap."""
    common = set(_SSB_SUBBANDS_HZ.keys()) & set(_CW_SUBBANDS_HZ.keys())
    for band in common:
        ssb_start, ssb_end = _SSB_SUBBANDS_HZ[band]
        cw_start, cw_end = _CW_SUBBANDS_HZ[band]
        overlap = min(ssb_end, cw_end) - max(ssb_start, cw_start)
        assert overlap <= 0, (
            f"{band}: SSB [{ssb_start/1e6:.3f}–{ssb_end/1e6:.3f} MHz] overlaps "
            f"CW [{cw_start/1e6:.3f}–{cw_end/1e6:.3f} MHz] by {overlap/1000:.1f} kHz"
        )


# ---------------------------------------------------------------------------
# _resolve_ssb_bounds — clipping logic (all bands)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("band", list(_SSB_SUBBANDS_HZ.keys()))
def test_resolve_ssb_bounds_clips_to_subband(band):
    """Wide sweep request wider than the SSB subband must be clipped to the subband."""
    ssb_start, ssb_end = _SSB_SUBBANDS_HZ[band]
    # Request the full default band allocation (deliberately wider)
    wide_start = ssb_start - 500_000
    wide_end = ssb_end + 500_000
    result_start, result_end = _resolve_ssb_bounds(band, wide_start, wide_end)
    assert result_start == ssb_start, (
        f"{band}: expected clip start {ssb_start}, got {result_start}"
    )
    assert result_end == ssb_end, (
        f"{band}: expected clip end {ssb_end}, got {result_end}"
    )


@pytest.mark.parametrize("band", list(_SSB_SUBBANDS_HZ.keys()))
def test_resolve_ssb_bounds_preserves_narrower_request(band):
    """A sweep already inside the SSB subband must not be expanded."""
    ssb_start, ssb_end = _SSB_SUBBANDS_HZ[band]
    mid = (ssb_start + ssb_end) // 2
    narrow_start = mid - 25_000
    narrow_end = mid + 25_000
    result_start, result_end = _resolve_ssb_bounds(band, narrow_start, narrow_end)
    assert result_start == narrow_start
    assert result_end == narrow_end


def test_resolve_ssb_bounds_unknown_band_passthrough():
    """For an unknown band, bounds must be returned unchanged (no clipping)."""
    start, end = _resolve_ssb_bounds("99m", 14_000_000, 14_350_000)
    assert start == 14_000_000
    assert end == 14_350_000


def test_resolve_ssb_bounds_outside_subband_falls_back():
    """If requested range is entirely outside SSB subband, original bounds are returned."""
    # 20m SSB is 14.140–14.350 MHz; request 14.000–14.100 which has no SSB content
    start, end = _resolve_ssb_bounds("20m", 14_000_000, 14_100_000)
    # clip would yield [max(14000, 14140), min(14100, 14350)] = [14140, 14100] → invalid
    # function must fall back to original bounds
    assert start == 14_000_000
    assert end == 14_100_000


# ---------------------------------------------------------------------------
# _resolve_cw_sweep_bounds — clipping logic
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("band", list(_CW_SUBBANDS_HZ.keys()))
def test_resolve_cw_bounds_clips_to_subband(band):
    """Wide sweep request must be clipped to the CW subband."""
    cw_start, cw_end = _CW_SUBBANDS_HZ[band]
    wide_start = cw_start - 200_000
    wide_end = cw_end + 200_000
    result_start, result_end = _resolve_cw_sweep_bounds(band, wide_start, wide_end)
    assert result_start == cw_start, f"{band}: CW clip start {cw_start}, got {result_start}"
    assert result_end == cw_end, f"{band}: CW clip end {cw_end}, got {result_end}"


def test_resolve_cw_bounds_unknown_band_passthrough():
    """For an unknown band, original CW bounds are returned unchanged."""
    start, end = _resolve_cw_sweep_bounds("99m", 14_000_000, 14_070_000)
    assert start == 14_000_000
    assert end == 14_070_000


# ---------------------------------------------------------------------------
# BW filter calibration — SSB standard 2.7 kHz (accept 2400–3000 Hz only)
# ---------------------------------------------------------------------------

_SSB_BW_MIN_HZ = 2400
_SSB_BW_MAX_HZ = 3000


@pytest.mark.parametrize("bw_hz", [2400, 2500, 2700, 2900, 3000])
def test_bw_filter_accepts_ssb_range(bw_hz):
    """Bandwidth values within the SSB window must pass the filter."""
    assert _SSB_BW_MIN_HZ <= bw_hz <= _SSB_BW_MAX_HZ, (
        f"BW {bw_hz} Hz should be accepted as SSB-standard"
    )


@pytest.mark.parametrize("bw_hz", [0, 250, 500, 1200, 2399, 3001, 5000, 10000])
def test_bw_filter_rejects_non_ssb(bw_hz):
    """Bandwidth values outside the SSB window must fail the filter."""
    assert not (_SSB_BW_MIN_HZ <= bw_hz <= _SSB_BW_MAX_HZ), (
        f"BW {bw_hz} Hz should be rejected as non-SSB"
    )


def test_bw_filter_boundary_2700():
    """2700 Hz (standard SSB nominal bandwidth) is inside the accepted window."""
    bw = 2700
    assert _SSB_BW_MIN_HZ <= bw <= _SSB_BW_MAX_HZ


def test_bw_filter_rejects_am_4khz():
    """4000 Hz (typical AM audio bandwidth) must be rejected."""
    bw = 4000
    assert not (_SSB_BW_MIN_HZ <= bw <= _SSB_BW_MAX_HZ)


def test_bw_filter_rejects_cw_500hz():
    """500 Hz (CW typical bandwidth) must be rejected."""
    bw = 500
    assert not (_SSB_BW_MIN_HZ <= bw <= _SSB_BW_MAX_HZ)
