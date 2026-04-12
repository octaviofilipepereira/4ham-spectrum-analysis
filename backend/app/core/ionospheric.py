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

def _estimate_fof2(sfi: float, utc_hour: float = 12.0, longitude: float = 0.0) -> float:
    """
    Estimate foF2 (critical frequency of F2 layer) from SFI.

    Method:
      1. Convert SFI → SSN (sunspot number) via ITU-R relation
      2. Compute noon foF2 using ITU-R P.1239 square-root model (mid-latitude)
      3. Compute Local Solar Time from UTC + QTH longitude
      4. Apply cos(χ) day/night scaling relative to local solar noon

    Reference values (mid-latitude, noon):
      SFI= 70 → foF2 ≈ 4.0 MHz
      SFI=120 → foF2 ≈ 8.2 MHz
      SFI=150 → foF2 ≈ 10.0 MHz
      SFI=200 → foF2 ≈ 11.5 MHz
    """
    if sfi <= 0:
        return 3.0  # safe minimum
    # SFI → SSN (ITU-R approximation)
    ssn = max(0.0, (sfi - 63.7) / 0.727)
    # Calibrated square-root model: noon mid-latitude foF2
    # foF2_noon ≈ 3.5 + 0.6 × √SSN  (validated against ionosonde data:
    # Juliusruh, Rome, El Arenosillo — SSN 0-150 range)
    fof2_noon = 3.5 + 0.6 * math.sqrt(ssn)
    # Local Solar Time: LST = UTC + longitude/15
    local_solar_hour = (utc_hour + longitude / 15.0) % 24.0
    # Hour angle from local solar noon
    hour_angle = (local_solar_hour - 12.0) * (math.pi / 12.0)
    chi_factor = max(0.0, math.cos(hour_angle))
    # Night floor: ~45% of noon value (mid-latitude, empirical)
    fof2 = fof2_noon * (0.45 + 0.55 * chi_factor)
    return round(max(fof2, 2.0), 2)


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


def _band_status(freq_mhz: float, fof2: float, kp: float,
                  local_solar_hour: float, sfi: float = 100.0) -> Dict[str, Any]:
    """Compute propagation status for a single band.

    Status values:
      - "Open"      — freq well below effective MUF, no absorption
      - "Marginal"  — freq between 80-100% of effective MUF
      - "Closed"    — freq above effective MUF
      - "Absorbed"  — daytime D-layer absorption blocks low-band DX

    Returns multi-zone distances for DR2W-style gradient patches:
      strong_km  — high-confidence coverage (S7-S9+)
      moderate_km — moderate coverage (S5-S7)
      weak_km    — fringe coverage (S3-S5)
    """
    muf_3000 = _muf_for_distance(fof2, 3000.0)

    # Apply geomagnetic degradation to effective MUF
    # Higher Kp → ionospheric disturbance → lower effective MUF
    geo_factor = max(0.0, 1.0 - (kp / 9.0))
    effective_muf = muf_3000 * (0.7 + 0.3 * geo_factor)  # 70-100% of MUF

    skip_km = _skip_distance_km(freq_mhz, fof2)

    # D-layer absorption: daytime kills low-frequency DX
    # D-layer exists when sun is above horizon (roughly LST 06-18)
    # and peaks at local noon.  Absorption per hop ∝ 1/f² and
    # reaches ~20-30 dB per hop at 7 MHz midday, making multi-hop
    # impossible and even single-hop very lossy.
    is_daytime = 6.0 <= local_solar_hour <= 18.0
    d_layer_cutoff_mhz = 5.5 if is_daytime else 0.0
    absorbed = is_daytime and freq_mhz < d_layer_cutoff_mhz

    # Solar elevation factor for D-layer: stronger near noon, weak at dawn/dusk
    _solar_elev = 0.0
    if is_daytime:
        # Sinusoidal model: peaks at 12, zero at 6 and 18
        _solar_elev = math.sin(math.pi * (local_solar_hour - 6.0) / 12.0)

    # Multi-hop distance computation based on MUF margin
    # Each F2 hop covers ~2000-3000 km (average ~2500 km).
    # Signal loses ~3-6 dB per hop, so practical paths rarely exceed 3 hops.
    # Only the best bands at solar maximum achieve 4 hops (~10000 km).
    _HOP_KM = 2500.0  # realistic average single-hop range
    if absorbed:
        status = "Absorbed"
        band_open = False
        max_hops = 0
    elif freq_mhz > effective_muf:
        status = "Closed"
        band_open = False
        max_hops = 0
    elif freq_mhz > effective_muf * 0.8:
        status = "Marginal"
        band_open = True
        max_hops = 1  # only single hop near MUF limit
    else:
        status = "Open"
        band_open = True
        margin = effective_muf / freq_mhz
        if margin >= 3.0:
            max_hops = 4  # exceptional — DX to antipodal region
        elif margin >= 2.2:
            max_hops = 3
        elif margin >= 1.5:
            max_hops = 2
        else:
            max_hops = 1

    # D-layer attenuation model (CCIR/VOACAP simplified)
    # D-layer absorption ∝ (1 + 0.004×SSN) / f^1.98 × cos^0.75(χ)
    # Simplified here as: abs_per_hop ≈ k / f² × solar_elev
    # where k scales with SSN (more sunspots → more D-layer ionization).
    # Reference: 7 MHz at noon, SSN=120 → ~18 dB/hop (kills multi-hop)
    #            14 MHz at noon, SSN=120 → ~4.5 dB/hop (limits to 2-3 hops)
    _ssn_for_dlayer = max(0.0, (sfi - 63.7) / 0.727) if sfi and sfi > 0 else 0.0
    if is_daytime and not absorbed and max_hops >= 1:
        d_layer_k = 500.0 + 4.0 * _ssn_for_dlayer  # ~970 at SSN=117
        abs_per_hop_db = (d_layer_k / (freq_mhz ** 2)) * _solar_elev
        # Tolerable total absorption: 15 dB (practical DX threshold)
        if abs_per_hop_db > 0:
            tolerable_hops = max(0, int(15.0 / abs_per_hop_db))
            max_hops = min(max_hops, tolerable_hops)

    max_distance_km = round(max_hops * _HOP_KM)

    # NVIS cap for low bands during peak daytime: even with 0 hops
    # from D-layer, 40m can still propagate via NVIS (~300-800 km)
    if is_daytime and not absorbed and freq_mhz < 10.0 and max_hops == 0:
        if freq_mhz >= 5.5:  # above D-layer cutoff but heavily absorbed
            max_distance_km = round(300 + max(0, freq_mhz - 5.5) * 150)  # ~300-975 km
            # Mark as still open (NVIS) even though 0 F2 hops

    # Three-zone model for gradient patches
    # Zones are proportions of max_distance_km (which already includes
    # D-layer and NVIS caps), so they always look right on the map.
    if max_distance_km > 0 and max_hops >= 3:
        strong_km = round(max_distance_km * 0.35)
        moderate_km = round(max_distance_km * 0.65)
        weak_km = max_distance_km
    elif max_distance_km > 0 and max_hops == 2:
        strong_km = round(max_distance_km * 0.40)
        moderate_km = round(max_distance_km * 0.70)
        weak_km = max_distance_km
    elif max_distance_km > 0:
        strong_km = round(max_distance_km * 0.40)
        moderate_km = round(max_distance_km * 0.70)
        weak_km = max_distance_km
    else:
        strong_km = 0
        moderate_km = 0
        weak_km = 0

    return {
        "open": band_open,
        "status": status,
        "skip_km": round(skip_km),
        "max_distance_km": max_distance_km,
        "strong_km": strong_km,
        "moderate_km": moderate_km,
        "weak_km": weak_km,
        "muf_at_3000km": round(effective_muf, 1),
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

                    self.last_update = datetime.now(timezone.utc).isoformat()
                    _log.info(
                        "Ionospheric data updated: Kp=%.1f (%s), SFI=%.0f",
                        self.kp or 0, self.kp_condition,
                        self.sfi or 0,
                    )
            except Exception as exc:
                _log.warning("Ionospheric fetch failed: %s", exc)

    def get_summary(self, latitude: float = 39.5, longitude: float = -8.0) -> Dict[str, Any]:
        """Return current ionospheric context with per-band status for a QTH."""
        kp = self.kp if self.kp is not None else 0.0
        sfi = self.sfi if self.sfi is not None else 0.0
        # Compute foF2 dynamically using QTH Local Solar Time
        now = datetime.now(timezone.utc)
        utc_hour = now.hour + now.minute / 60.0
        fof2 = _estimate_fof2(sfi, utc_hour, longitude)
        local_solar_hour = (utc_hour + longitude / 15.0) % 24.0

        bands: Dict[str, Dict] = {}
        for band_name, freq_mhz in _HF_BANDS_MHZ.items():
            bands[band_name] = _band_status(freq_mhz, fof2, kp, local_solar_hour, sfi)

        return {
            "kp": kp,
            "kp_condition": self.kp_condition,
            "sfi": sfi,
            "fof2_estimated_mhz": fof2,
            "qth": {"lat": latitude, "lon": longitude},
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
