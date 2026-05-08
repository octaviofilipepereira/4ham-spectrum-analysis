# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
Tests for satellite validators (TLE + catalog JSON parsing).
"""
import pytest
from app.satellite.validators import parse_tle_text, parse_catalog_json, ValidationError


VALID_3LINE_TLE = (
    b"ISS (ZARYA)\n"
    b"1 25544U 98067A   24100.50000000  .00003000  00000-0  60000-4 0  9995\n"
    b"2 25544  51.6400 100.0000 0001234  90.0000 270.0000 15.50000000000012\n"
)

VALID_2LINE_TLE = (
    b"1 25544U 98067A   24100.50000000  .00003000  00000-0  60000-4 0  9995\n"
    b"2 25544  51.6400 100.0000 0001234  90.0000 270.0000 15.50000000000012\n"
)


def test_parse_3line_tle_returns_entry():
    result = parse_tle_text(VALID_3LINE_TLE)
    assert len(result) == 1
    sat = result[0]
    assert sat["name"] == "ISS (ZARYA)"
    assert sat["line1"].startswith("1 25544")
    assert sat["line2"].startswith("2 25544")


def test_parse_2line_tle_synthesises_name():
    result = parse_tle_text(VALID_2LINE_TLE)
    assert len(result) == 1
    assert result[0]["name"].startswith("NORAD-")
    assert result[0]["line1"].startswith("1 25544")


def test_parse_multiple_tles():
    second = VALID_3LINE_TLE.replace(b"25544", b"99999").replace(b"ISS (ZARYA)", b"FAKESAT-1")
    raw = VALID_3LINE_TLE + second
    result = parse_tle_text(raw)
    assert len(result) == 2


def test_tle_size_limit():
    big = VALID_3LINE_TLE * 10_000   # well over 1 MB
    with pytest.raises(ValidationError, match="too large"):
        parse_tle_text(big)


def test_tle_non_ascii_rejected():
    bad = "Sat\u00e9lite\n".encode("utf-8") + VALID_3LINE_TLE[10:]
    with pytest.raises(ValidationError, match="ASCII"):
        parse_tle_text(bad)


def test_tle_injection_name_sanitised():
    raw = (
        b"<script>alert(1)</script>\n"
        b"1 25544U 98067A   24100.50000000  .00003000  00000-0  60000-4 0  9995\n"
        b"2 25544  51.6400 100.0000 0001234  90.0000 270.0000 15.50000000000012\n"
    )
    result = parse_tle_text(raw)
    assert "<" not in result[0]["name"]


def test_tle_malformed_after_name_raises():
    bad = (
        b"BADSAT\n"
        b"9 25544U 98067A   24100.50000000  .00003000  00000-0  60000-4 0  9995\n"
        b"2 25544  51.6400 100.0000 0001234  90.0000 270.0000 15.50000000000012\n"
    )
    with pytest.raises(ValidationError, match="malformed"):
        parse_tle_text(bad)


def test_tle_empty_input_raises():
    with pytest.raises(ValidationError, match="No valid TLE"):
        parse_tle_text(b"")


# ── Catalog JSON parse ─────────────────────────────────────────────────────────

VALID_CATALOG_LIST = b'[{"norad_cat_id": 25544, "name": "ISS", "status": "alive"}]'
VALID_CATALOG_OBJ = b'{"satellites": [{"norad_cat_id": 43874, "name": "FO-29", "status": "alive"}]}'


def test_catalog_list_form():
    result = parse_catalog_json(VALID_CATALOG_LIST)
    assert len(result) == 1
    assert result[0]["norad_cat_id"] == 25544


def test_catalog_object_form():
    result = parse_catalog_json(VALID_CATALOG_OBJ)
    assert len(result) == 1
    assert result[0]["name"] == "FO-29"


def test_catalog_size_limit():
    # Need to exceed 5 MB to hit the size guard before JSON parse
    big = b"[" + (b'{"norad_cat_id":1,"name":"x"},' * 200_000) + b'{"norad_cat_id":2,"name":"y"}]'
    with pytest.raises(ValidationError, match="too large"):
        parse_catalog_json(big)


def test_catalog_non_list_content():
    with pytest.raises(ValidationError):
        parse_catalog_json(b'"just a string"')


def test_catalog_invalid_json():
    with pytest.raises(ValidationError, match="Invalid JSON"):
        parse_catalog_json(b"not json at all")


def test_catalog_empty_list_raises():
    with pytest.raises(ValidationError, match="No satellite"):
        parse_catalog_json(b"[]")
