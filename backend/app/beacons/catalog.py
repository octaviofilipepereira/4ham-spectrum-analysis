# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
NCDXF/IARU International Beacon Project — static catalog & schedule.

Reference: https://www.ncdxf.org/beacon/

Each of the 18 beacons transmits for exactly 10 s, then steps to the next
band. A full rotation across the 18 beacons on a single band takes
180 s (3 minutes). The rotation is rigidly synchronised to UTC: the slot
boundary always falls on multiples of 10 s past the minute.

Schedule formula (verified against the published NCDXF table):

    slot_index   = (epoch_utc_seconds % 180) // 10        # 0..17
    band_index   = 0 (14.100) .. 4 (28.200)
    beacon_index = (slot_index - band_index) % 18

Equivalently, beacon `i` transmits on band `b` at slot `(i + b) mod 18`.

Slot internal timing (the same for every beacon, every band):

    t = 0.0 s .. ~1.0 s      callsign in CW @ 22 WPM
    t ≈ 1.0 s .. ~2.0 s      dash @ 100 W
    t ≈ 2.3 s .. ~3.3 s      dash @ 10 W
    t ≈ 3.6 s .. ~4.6 s      dash @ 1 W
    t ≈ 4.9 s .. ~5.9 s      dash @ 100 mW
    t ≈ 5.9 s .. 10.0 s      silence (guard)

Detected dash count (highest sensitivity reached) is the canonical
propagation indicator for this module: if the 100 mW dash is detected,
SNR on the path is ≥ ~30 dB above the noise floor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final


# ── Beacon list (canonical order from NCDXF) ──────────────────────────────────

@dataclass(frozen=True)
class Beacon:
    index: int          # 0..17 — fixed position in the rotation
    callsign: str       # CW identifier transmitted at slot start
    location: str       # Human-readable location (city, country)
    qth_locator: str    # Maidenhead grid (6 chars)
    lat: float          # Decimal degrees, +N
    lon: float          # Decimal degrees, +E
    status: str         # "active" | "off_air" | "intermittent"
    notes: str = ""


BEACONS: Final[tuple[Beacon, ...]] = (
    Beacon(0,  "4U1UN",  "United Nations HQ, New York, USA", "FN30as",  40.7489,  -73.9680, "intermittent",
           "Often off-air pending UN building maintenance"),
    Beacon(1,  "VE8AT",  "Eureka, Nunavut, Canada",          "EQ79ax",  79.9833,  -85.9333, "off_air",
           "Long-term off-air (Arctic site, no maintenance)"),
    Beacon(2,  "W6WX",   "Mt Umunhum, California, USA",      "CM97bd",  37.1583, -121.8983, "active"),
    Beacon(3,  "KH6RS",  "Maui, Hawaii, USA",                "BL10ts",  20.7833, -156.4667, "active"),
    Beacon(4,  "ZL6B",   "Masterton, New Zealand",           "RE78tw", -40.9000,  175.6167, "active"),
    Beacon(5,  "VK6RBP", "Rolystone, Western Australia",     "OF87av", -32.0833,  116.0500, "active"),
    Beacon(6,  "JA2IGY", "Mt Asama, Japan",                  "PM84jk",  34.4500,  136.7833, "active"),
    Beacon(7,  "RR9O",   "Novosibirsk, Russia",              "NO14kx",  54.9833,   82.8833, "active"),
    Beacon(8,  "VR2B",   "Hong Kong",                        "OL72bg",  22.2667,  114.1500, "off_air",
           "Off-air; some sources list B4B (China) in this slot"),
    Beacon(9,  "4S7B",   "Colombo, Sri Lanka",               "MJ96wv",   6.9000,   79.8667, "active"),
    Beacon(10, "ZS6DN",  "Pretoria, South Africa",           "KG44dc", -25.9000,   28.3000, "active"),
    Beacon(11, "5Z4B",   "Kilifi, Kenya",                    "KI94kw",  -3.6333,   39.8500, "off_air",
           "Off-air for several years"),
    Beacon(12, "4X6TU",  "Tel Aviv, Israel",                 "KM72jb",  32.0500,   34.7833, "active"),
    Beacon(13, "OH2B",   "Espoo, Finland",                   "KP20ie",  60.2167,   24.6500, "active"),
    Beacon(14, "CS3B",   "Madeira, Portugal",                "IM12or",  32.6500,  -16.9000, "active",
           "Operated by ARRM (Madeira)"),
    Beacon(15, "LU4AA",  "Buenos Aires, Argentina",          "GF05tj", -34.6000,  -58.4500, "active"),
    Beacon(16, "OA4B",   "Lima, Peru",                       "FH17mw", -12.0500,  -77.0500, "off_air",
           "Off-air for several years"),
    Beacon(17, "YV5B",   "Caracas, Venezuela",               "FK60nk",  10.5000,  -66.9000, "off_air",
           "Off-air"),
)
assert len(BEACONS) == 18, "NCDXF rotation requires exactly 18 beacons"


# ── Bands ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BeaconBand:
    index: int          # 0..4
    name: str           # "20m", "17m", "15m", "12m", "10m"
    freq_hz: int        # carrier frequency the beacon transmits on


BANDS: Final[tuple[BeaconBand, ...]] = (
    BeaconBand(0, "20m", 14_100_000),
    BeaconBand(1, "17m", 18_110_000),
    BeaconBand(2, "15m", 21_150_000),
    BeaconBand(3, "12m", 24_930_000),
    BeaconBand(4, "10m", 28_200_000),
)
assert len(BANDS) == 5


# ── Timing constants ──────────────────────────────────────────────────────────

SLOT_SECONDS: Final[int]      = 10
SLOTS_PER_CYCLE: Final[int]   = 18           # one full rotation per band
CYCLE_SECONDS: Final[int]     = SLOTS_PER_CYCLE * SLOT_SECONDS   # 180 s

CW_ID_WPM: Final[int]         = 22
CW_ID_END_S: Final[float]     = 1.0          # callsign roughly fits in <1 s

# Dash windows inside the 10 s slot. Conservative, matches NCDXF spec.
# (start_s, end_s, nominal_power_w)
DASH_WINDOWS: Final[tuple[tuple[float, float, float], ...]] = (
    (1.0, 2.0, 100.0),    # 100 W
    (2.3, 3.3,  10.0),    # 10 W
    (3.6, 4.6,   1.0),    # 1 W
    (4.9, 5.9,   0.1),    # 100 mW
)
assert len(DASH_WINDOWS) == 4


# ── Schedule lookup ───────────────────────────────────────────────────────────

def beacon_at(slot_index: int, band_index: int) -> Beacon:
    """Return the beacon transmitting at the given (slot, band) pair.

    `slot_index` is the slot number within the 3-minute cycle (0..17),
    obtainable from :func:`current_slot_index` (or any UTC timestamp).
    `band_index` selects one of the five NCDXF bands (0..4).
    """
    if not 0 <= band_index < len(BANDS):
        raise IndexError(f"band_index out of range: {band_index}")
    if not 0 <= slot_index < SLOTS_PER_CYCLE:
        raise IndexError(f"slot_index out of range: {slot_index}")
    return BEACONS[(slot_index - band_index) % SLOTS_PER_CYCLE]


def slot_for(beacon_index: int, band_index: int) -> int:
    """Inverse of :func:`beacon_at` — slot at which beacon `i` transmits on band `b`."""
    if not 0 <= beacon_index < len(BEACONS):
        raise IndexError(f"beacon_index out of range: {beacon_index}")
    if not 0 <= band_index < len(BANDS):
        raise IndexError(f"band_index out of range: {band_index}")
    return (beacon_index + band_index) % SLOTS_PER_CYCLE


def current_slot_index(now_utc: datetime | None = None) -> int:
    """Current slot index (0..17) within the 3-minute cycle."""
    now = now_utc or datetime.now(timezone.utc)
    epoch_s = int(now.timestamp())
    return (epoch_s % CYCLE_SECONDS) // SLOT_SECONDS


def current_cycle_window(now_utc: datetime | None = None) -> tuple[datetime, datetime]:
    """UTC start/end datetimes for the current 3-minute NCDXF cycle."""
    now = now_utc or datetime.now(timezone.utc)
    epoch_s = int(now.timestamp())
    cycle_start_epoch = epoch_s - (epoch_s % CYCLE_SECONDS)
    cycle_start = datetime.fromtimestamp(cycle_start_epoch, tz=timezone.utc)
    return cycle_start, cycle_start + timedelta(seconds=CYCLE_SECONDS)


def seconds_into_slot(now_utc: datetime | None = None) -> float:
    """Seconds elapsed since the current slot started (0.0 .. 10.0)."""
    now = now_utc or datetime.now(timezone.utc)
    return now.timestamp() % SLOT_SECONDS


def next_slot_start(now_utc: datetime | None = None) -> datetime:
    """UTC datetime of the next slot boundary (for sleep alignment)."""
    now = now_utc or datetime.now(timezone.utc)
    epoch = now.timestamp()
    next_epoch = (int(epoch) // SLOT_SECONDS + 1) * SLOT_SECONDS
    return datetime.fromtimestamp(next_epoch, tz=timezone.utc)


def all_active_beacons() -> tuple[Beacon, ...]:
    """Beacons currently considered transmitting (status == 'active')."""
    return tuple(b for b in BEACONS if b.status == "active")
