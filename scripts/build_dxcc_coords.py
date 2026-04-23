# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

#!/usr/bin/env python3
"""
build_dxcc_coords.py
====================
Downloads cty.dat from AD1C (country-files.com) and converts it to
prefixes/dxcc_coords.json used by the propagation map feature.

cty.dat format (per line pair):
  Country name: CQ_zone: ITU_zone: continent: lat: lon: utc_offset: PREFIX:
      alias1,alias2,...;

IMPORTANT: cty.dat lon sign convention is INVERTED vs GeoJSON standard:
  positive = West, negative = East → must be negated for standard geo use.

Usage:
  python3 scripts/build_dxcc_coords.py
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

CTY_URL = "https://www.country-files.com/cty/cty.dat"
OUT_PATH = Path(__file__).parent.parent / "prefixes" / "dxcc_coords.json"

CONTINENT_NAMES = {
    "EU": "Europe",
    "AS": "Asia",
    "AF": "Africa",
    "NA": "North America",
    "SA": "South America",
    "OC": "Oceania",
    "AN": "Antarctica",
}


def download_cty(url: str) -> str:
    print(f"Downloading {url} ...", flush=True)
    with urllib.request.urlopen(url, timeout=30) as resp:
        raw = resp.read().decode("latin-1")
    print(f"  Downloaded {len(raw):,} bytes", flush=True)
    return raw


def parse_cty(raw: str) -> list[dict]:
    """Parse cty.dat into list of DXCC entities."""
    entries = []

    # Split into blocks: header line + continuation lines ending with ;
    blocks = re.split(r"\n(?=[A-Z])", raw.strip())

    header_re = re.compile(
        r"^(.+?):\s+"       # country name
        r"(\d+):\s+"        # CQ zone
        r"(\d+):\s+"        # ITU zone
        r"([A-Z]{2}):\s+"   # continent
        r"(-?\d+\.\d+):\s+" # lat
        r"(-?\d+\.\d+):\s+" # lon (sign inverted in cty.dat)
        r"(-?\d+\.?\d*):\s+" # UTC offset
        r"([^:]+):",        # main prefix
        re.MULTILINE
    )

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        m = header_re.match(block)
        if not m:
            continue

        country = m.group(1).strip()
        cq_zone = int(m.group(2))
        itu_zone = int(m.group(3))
        continent_code = m.group(4).strip()
        lat = float(m.group(5))
        lon_cty = float(m.group(6))
        utc_offset = float(m.group(7))
        main_prefix = m.group(8).strip()

        # cty.dat lon is sign-inverted → negate for standard GeoJSON (E positive)
        lon = -lon_cty

        # Collect all prefixes/aliases from continuation lines
        rest = block[m.end():]
        alias_raw = re.sub(r"\s+", "", rest).rstrip(";")
        aliases = []
        for token in alias_raw.split(","):
            token = token.strip()
            if not token:
                continue
            # Skip exact-match exceptions (start with =)
            if token.startswith("="):
                continue
            # Normalise: strip trailing /P /M etc for prefix list
            token = re.sub(r"/[A-Z0-9]+$", "", token)
            if token and token not in aliases:
                aliases.append(token)

        # Build sorted prefix list: main prefix first, then aliases
        all_prefixes = [main_prefix]
        for a in aliases:
            if a != main_prefix and a not in all_prefixes:
                all_prefixes.append(a)

        entries.append({
            "country": country,
            "main_prefix": main_prefix,
            "prefixes": all_prefixes,
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "continent": continent_code,
            "continent_name": CONTINENT_NAMES.get(continent_code, continent_code),
            "cq_zone": cq_zone,
            "itu_zone": itu_zone,
            "utc_offset": utc_offset,
        })

    return entries


def build_prefix_index(entries: list[dict]) -> dict:
    """Build flat prefix→entry index (longest prefix match friendly).
    
    Sorted by prefix length descending so longest-match wins at lookup time.
    """
    index = {}
    for entry in entries:
        for pfx in entry["prefixes"]:
            if pfx not in index:
                index[pfx] = {
                    "country": entry["country"],
                    "main_prefix": entry["main_prefix"],
                    "lat": entry["lat"],
                    "lon": entry["lon"],
                    "continent": entry["continent"],
                    "continent_name": entry["continent_name"],
                    "cq_zone": entry["cq_zone"],
                    "itu_zone": entry["itu_zone"],
                }
    return index


def main():
    raw = download_cty(CTY_URL)
    entries = parse_cty(raw)
    print(f"  Parsed {len(entries)} DXCC entities", flush=True)

    index = build_prefix_index(entries)
    print(f"  Built index with {len(index)} prefix entries", flush=True)

    out = {
        "meta": {
            "source": CTY_URL,
            "description": "DXCC entity prefix→coordinates index, generated from cty.dat by AD1C",
            "lon_convention": "GeoJSON standard (East positive)",
            "note": "Use longest-prefix-match when resolving callsigns",
            "generated_at": __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "entity_count": len(entries),
            "prefix_count": len(index),
        },
        "entities": entries,
        "index": index,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"  Written {OUT_PATH} ({size_kb:.1f} KB)", flush=True)

    # Quick sanity checks
    checks = [
        ("CT", "Portugal"),
        ("DL", "Germany"),
        ("W", "United States"),
        ("JA", "Japan"),
        ("VK", "Australia"),
        ("PY", "Brazil"),
        ("ZS", "South Africa"),
    ]
    print("\nSanity checks:", flush=True)
    for pfx, expected in checks:
        entry = index.get(pfx)
        if entry:
            status = "✓" if expected.lower() in entry["country"].lower() else "?"
            print(f"  {status} {pfx:6s} → {entry['country']:30s} lat={entry['lat']:7.2f} lon={entry['lon']:8.2f}", flush=True)
        else:
            print(f"  ✗ {pfx:6s} → NOT FOUND", flush=True)


if __name__ == "__main__":
    main()
