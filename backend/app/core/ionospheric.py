# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

"""
Ionospheric Context Service
============================
Periodic fetch of space weather indices from NOAA SWPC and
computation of band-specific MUF estimates.

Data sources (public, no auth):
  - Kp index  : https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json
  - SFI 10.7cm: https://services.swpc.noaa.gov/json/f107_cm_flux.json
"""

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

_log = logging.getLogger("uvicorn.error")

# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════

_NOAA_KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
_NOAA_SFI_URL = "https://services.swpc.noaa.gov/json/f107_cm_flux.json"

_FETCH_INTERVAL_S = 900  # 15 minutes
_HTTP_TIMEOUT_S = 15

# Amateur HF bands — centre frequency in MHz
_HF_BANDS_MHZ: Dict[str, float] = {
    "160m": 1.9,
    "80m": 3.6,
    "60m": 5.35,
    "40m": 7.1,
    "30m": 10.125,
    "20m": 14.175,
    "17m": 18.118,
    "15m": 21.225,
    "12m": 24.94,
    "10m": 28.5,
    "6m": 50.15,
}

# Virtual height of F2 layer (km) — standard ionospheric modelling value
_HV_F2_KM = 300.0


# ═══════════════════════════════════════════════════════════════════
# Kp interpretation
# ═══════════════════════════════════════════════════════════════════

def _kp_condition(kp: float) -> str:
    if kp < 2:
        return "Quiet"
    if kp < 4:
        return "Unsettled"
    if kp < 5:
        return "Active"
    if kp < 6:
        return "Minor storm"
    if kp < 7:
        return "Moderate storm"
    if kp < 8:
        return "Strong storm"
    return "Severe storm"


# ═══════════════════════════════════════════════════════════════════
# Physics: SFI → foF2 → MUF estimates
# ═══════════════════════════════════════════════════════════════════

def _estimate_fof2(sfi: float) -> float:
    """
    Estimate foF2 (critical frequency of F2 layer) from SFI using the
    empirical Kouris–Muggleton relation:

        foF2 ≈ 0.121 * SFI^0.6   (MHz, mid-latitude daytime average)

    This is a simplified daytime mid-latitude approximation.
    Night-time values are typically 30-50% lower.
    """
    if sfi <= 0:
        return 3.0  # safe minimum
    return 0.121 * (sfi ** 0.6)


def _muf_for_distance(fof2: float, distance_km: float) -> float:
    """
    Estimate MUF for a given great-circle distance using the secant law:

        MUF ≈ foF2 / cos(arctan(d / (2 * hv)))

    where d = ground distance, hv = virtual height of F2 layer.
    For multi-hop paths (> ~4000 km), MUF is approximately foF2 * 3.6.
    """
    if fof2 <= 0:
        return 0.0
    if distance_km <= 0:
        return fof2
    # Single-hop geometry
    half_d = distance_km / 2.0
    # Earth radius correction for longer paths
    R_EARTH = 6371.0
    # Elevation angle at the ground station
    theta = math.atan2(half_d, _HV_F2_KM + (half_d ** 2) / (2 * R_EARTH))
    sec_theta = 1.0 / max(math.cos(theta), 0.1)
    muf = fof2 * sec_theta
    # Cap at practical maximum (~3.6 × foF2 for long paths)
    return min(muf, fof2 * 3.6)


def _skip_distance_km(freq_mhz: float, fof2: float) -> float:
    """
    Estimate skip distance for a given frequency and foF2.

        d_skip ≈ 2 * hv * sqrt((f/foF2)² - 1)

    If freq < foF2 the band has no skip zone (NVIS possible).
    """
    if fof2 <= 0 or freq_mhz <= fof2:
        return 0.0
    ratio = freq_mhz / fof2
    return 2.0 * _HV_F2_KM * math.sqrt(ratio ** 2 - 1.0)


def _band_status(freq_mhz: float, fof2: float, kp: float) -> Dict[str, Any]:
    """Compute propagation status for a single band."""
    muf_3000 = _muf_for_distance(fof2, 3000.0)
    skip_km = _skip_distance_km(freq_mhz, fof2)

    # Max usable single-hop distance (~4000 km for F2)
    max_distance_km = 4000.0 if freq_mhz <= muf_3000 else 0.0

    # Is the band theoretically open?
    band_open = freq_mhz <= muf_3000

    # Geomagnetic degradation factor
    geo_factor = max(0.0, 1.0 - (kp / 9.0))

    return {
        "open": band_open,
        "skip_km": round(skip_km),
        "max_distance_km": round(max_distance_km) if band_open else 0,
        "muf_at_3000km": round(muf_3000, 1),
        "geo_factor": round(geo_factor, 2),
    }


# ═══════════════════════════════════════════════════════════════════
# Ionospheric Cache Singleton
# ═══════════════════════════════════════════════════════════════════

class IonosphericCache:
    """In-memory cache for space weather data, refreshed periodically."""

    def __init__(self) -> None:
        self.kp: Optional[float] = None
        self.kp_condition: str = "Unknown"
        self.sfi: Optional[float] = None
        self.fof2_est: Optional[float] = None
        self.last_update: Optional[str] = None
        self._lock = asyncio.Lock()

    async def refresh(self) -> None:
        """Fetch latest Kp and SFI from NOAA SWPC."""
        async with self._lock:
            try:
                async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as client:
                    # Fetch Kp
                    kp_resp = await client.get(
                        _NOAA_KP_URL,
                        headers={"User-Agent": "4ham-spectrum-analysis/1.0"},
                    )
                    if kp_resp.status_code == 200:
                        kp_data = kp_resp.json()
                        # Data is array of objects; last entry is most recent
                        # First row is header, skip it
                        if len(kp_data) >= 2:
                            latest = kp_data[-1]
                            kp_val = float(latest.get("Kp", 0))
                            self.kp = round(kp_val, 1)
                            self.kp_condition = _kp_condition(kp_val)

                    # Fetch SFI
                    sfi_resp = await client.get(
                        _NOAA_SFI_URL,
                        headers={"User-Agent": "4ham-spectrum-analysis/1.0"},
                    )
                    if sfi_resp.status_code == 200:
                        sfi_data = sfi_resp.json()
                        if sfi_data:
                            latest = sfi_data[-1]
                            sfi_val = float(latest.get("flux", 0))
                            if sfi_val > 0:
                                self.sfi = round(sfi_val, 1)
                                self.fof2_est = round(_estimate_fof2(sfi_val), 2)

                    self.last_update = datetime.now(timezone.utc).isoformat()
                    _log.info(
                        "Ionospheric data updated: Kp=%.1f (%s), SFI=%.0f, foF2≈%.1f MHz",
                        self.kp or 0, self.kp_condition,
                        self.sfi or 0, self.fof2_est or 0,
                    )
            except Exception as exc:
                _log.warning("Ionospheric fetch failed: %s", exc)

    def get_summary(self) -> Dict[str, Any]:
        """Return current ionospheric context with per-band status."""
        kp = self.kp if self.kp is not None else 0.0
        sfi = self.sfi if self.sfi is not None else 0.0
        fof2 = self.fof2_est if self.fof2_est is not None else 3.0

        bands: Dict[str, Dict] = {}
        for band_name, freq_mhz in _HF_BANDS_MHZ.items():
            bands[band_name] = _band_status(freq_mhz, fof2, kp)

        return {
            "kp": kp,
            "kp_condition": self.kp_condition,
            "sfi": sfi,
            "fof2_estimated_mhz": fof2,
            "bands": bands,
            "last_update": self.last_update,
            "source": "NOAA SWPC",
        }


# Module-level singleton
ionospheric_cache = IonosphericCache()


# ═══════════════════════════════════════════════════════════════════
# Background refresh loop
# ═══════════════════════════════════════════════════════════════════

async def ionospheric_refresh_loop() -> None:
    """Background task: refresh ionospheric data every 15 minutes."""
    await asyncio.sleep(5)  # let server finish startup
    while True:
        await ionospheric_cache.refresh()
        await asyncio.sleep(_FETCH_INTERVAL_S)
