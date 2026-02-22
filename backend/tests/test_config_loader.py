# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 00:34:50 UTC

import pytest

from app.config.loader import (
    ConfigError,
    apply_region_profile_to_scan,
    load_region_profile,
    load_scan_request,
)


def test_load_scan_request_inline_payload():
    payload = {
        "scan": {
            "band": "20m",
            "start_hz": 14000000,
            "end_hz": 14350000,
            "step_hz": 2000,
            "dwell_ms": 250,
            "mode": "auto"
        }
    }
    loaded = load_scan_request(payload)
    assert loaded["scan"]["band"] == "20m"
    assert loaded["scan"]["step_hz"] == 2000


def test_load_scan_request_from_yaml_file(tmp_path):
    config_file = tmp_path / "scan.yaml"
    config_file.write_text(
        """
scan:
  band: 20m
  start_hz: 14000000
  end_hz: 14350000
  step_hz: 2000
  dwell_ms: 250
  mode: auto
""".strip(),
        encoding="utf-8"
    )

    loaded = load_scan_request({"scan_config_path": str(config_file), "device": "rtl_sdr"})
    assert loaded["scan"]["end_hz"] == 14350000
    assert loaded["device"] == "rtl_sdr"


def test_load_scan_request_invalid_payload_raises():
    with pytest.raises(ConfigError):
        load_scan_request({"scan": {"band": "20m"}})


def test_load_scan_request_allows_wrapper_keys():
    payload = {
        "device": "rtl_sdr",
        "region_profile_path": "config/region_profile_example.yaml",
        "scan": {
            "band": "20m",
            "start_hz": 14000000,
            "end_hz": 14350000,
            "step_hz": 2000,
            "dwell_ms": 250,
            "mode": "auto"
        }
    }
    loaded = load_scan_request(payload)
    assert loaded["device"] == "rtl_sdr"
    assert loaded["region_profile_path"] == "config/region_profile_example.yaml"


def test_apply_region_profile_to_scan_sets_missing_bounds():
    profile = load_region_profile("config/region_profile_example.yaml")
    scan = {
        "band": "20m",
        "start_hz": 0,
        "end_hz": 0,
        "step_hz": 2000,
        "dwell_ms": 250,
        "mode": "auto"
    }

    applied = apply_region_profile_to_scan(scan, profile)

    assert applied is True
    assert scan["start_hz"] == 14000000
    assert scan["end_hz"] == 14350000
