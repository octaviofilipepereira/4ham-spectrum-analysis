# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
Satellite module — TLE upload and catalog upload validators.

All parsing is done in memory — no files written to disk.
"""

import json
import re
import unicodedata
from typing import Any

# ── Constants ─────────────────────────────────────────────────────────────────

_TLE_MAX_BYTES   = 1 * 1024 * 1024   # 1 MB
_CAT_MAX_BYTES   = 5 * 1024 * 1024   # 5 MB
_NAME_SAFE_RE    = re.compile(r"[^\w\s/()\-.]", re.UNICODE)  # strip unsafe chars
_TLE_LINE1_RE    = re.compile(r"^1 \d{5}[A-Z ] ")
_TLE_LINE2_RE    = re.compile(r"^2 \d{5} ")


class ValidationError(ValueError):
    pass


# ── TLE validation ─────────────────────────────────────────────────────────────

def parse_tle_text(raw: bytes) -> list[dict[str, str]]:
    """
    Parse a raw TLE file (2-line or 3-line format, up to _TLE_MAX_BYTES).

    Returns list of dicts: {"name": str, "line1": str, "line2": str}.
    Raises ValidationError on bad input.
    """
    if len(raw) > _TLE_MAX_BYTES:
        raise ValidationError(f"TLE file too large (max {_TLE_MAX_BYTES // 1024} KB)")

    try:
        text = raw.decode("ascii", errors="strict")
    except (UnicodeDecodeError, ValueError):
        raise ValidationError("TLE file must be ASCII-only")

    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("#")]

    satellites: list[dict[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _TLE_LINE1_RE.match(line):
            # 2-line format: line1 + line2 (no name)
            if i + 1 >= len(lines):
                raise ValidationError(f"TLE line 1 at position {i} has no following line 2")
            line2 = lines[i + 1]
            if not _TLE_LINE2_RE.match(line2):
                raise ValidationError(f"Expected TLE line 2 after line 1 at position {i}")
            satellites.append({"name": f"NORAD-{line[2:7].strip()}", "line1": line, "line2": line2})
            i += 2
        elif _TLE_LINE2_RE.match(line):
            raise ValidationError(f"Unexpected TLE line 2 without preceding line 1 at position {i}")
        else:
            # Treat as satellite name line (3-line format)
            name = _sanitize_name(line)
            if i + 2 >= len(lines):
                raise ValidationError(f"Name '{name}' at position {i} has no following TLE lines")
            l1, l2 = lines[i + 1], lines[i + 2]
            if not _TLE_LINE1_RE.match(l1) or not _TLE_LINE2_RE.match(l2):
                raise ValidationError(f"TLE lines after name '{name}' at position {i} are malformed")
            satellites.append({"name": name, "line1": l1, "line2": l2})
            i += 3

    if not satellites:
        raise ValidationError("No valid TLE entries found in the uploaded file")
    return satellites


# ── Catalog JSON validation ───────────────────────────────────────────────────

def parse_catalog_json(raw: bytes) -> list[dict[str, Any]]:
    """
    Parse a SatNOGS-format catalog JSON (up to _CAT_MAX_BYTES).

    Accepts either:
    - A list of satellite objects directly
    - An object with a "satellites" key (4ham snapshot format)

    Returns list of raw satellite dicts (validated minimally).
    Raises ValidationError on bad input.
    """
    if len(raw) > _CAT_MAX_BYTES:
        raise ValidationError(f"Catalog file too large (max {_CAT_MAX_BYTES // (1024*1024)} MB)")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid JSON: {exc}")

    if isinstance(data, list):
        satellites = data
    elif isinstance(data, dict) and "satellites" in data:
        satellites = data["satellites"]
    else:
        raise ValidationError("Expected a JSON array or an object with a 'satellites' key")

    if not isinstance(satellites, list):
        raise ValidationError("'satellites' must be a JSON array")

    validated: list[dict[str, Any]] = []
    for i, sat in enumerate(satellites):
        if not isinstance(sat, dict):
            raise ValidationError(f"Entry {i} is not an object")
        norad = sat.get("norad_cat_id") or sat.get("norad_id")
        if norad is None:
            raise ValidationError(f"Entry {i} missing 'norad_cat_id' / 'norad_id'")
        try:
            norad = int(norad)
        except (TypeError, ValueError):
            raise ValidationError(f"Entry {i} norad_id is not an integer")
        name = _sanitize_name(str(sat.get("name") or f"NORAD-{norad}"))
        validated.append({**sat, "norad_cat_id": norad, "name": name})

    if not validated:
        raise ValidationError("No satellite entries found in catalog")

    return validated


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sanitize_name(name: str) -> str:
    """Strip characters outside alphanumeric + safe punctuation and normalise Unicode."""
    name = unicodedata.normalize("NFKC", name)
    name = _NAME_SAFE_RE.sub("", name)
    return name.strip()[:80]
