# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 00:34:50 UTC

import json
from pathlib import Path

import yaml
from jsonschema import ValidationError, validate


class ConfigError(ValueError):
    pass


_ROOT_DIR = Path(__file__).resolve().parents[3]
_SCAN_SCHEMA_PATH = _ROOT_DIR / "config" / "scan_config.schema.json"
_REGION_SCHEMA_PATH = _ROOT_DIR / "config" / "region_profile.schema.json"


def _load_json(path: Path):
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as fp:
        return yaml.safe_load(fp)


def _resolve_config_path(config_path: str) -> Path:
    candidate = Path(config_path).expanduser()
    if not candidate.is_absolute():
        candidate = (_ROOT_DIR / candidate).resolve()
    if not candidate.exists() or not candidate.is_file():
        raise ConfigError(f"Configuration file not found: {config_path}")
    return candidate


def _load_document(path: Path):
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        data = _load_yaml(path)
    elif suffix == ".json":
        data = _load_json(path)
    else:
        try:
            data = _load_json(path)
        except Exception:
            data = _load_yaml(path)
    if not isinstance(data, dict):
        raise ConfigError(f"Config root must be an object: {path}")
    return data


def _validate_schema(data: dict, schema_path: Path, label: str):
    schema = _load_json(schema_path)
    try:
        validate(instance=data, schema=schema)
    except ValidationError as exc:
        message = exc.message
        if exc.path:
            message = f"{'/'.join(str(item) for item in exc.path)}: {message}"
        raise ConfigError(f"Invalid {label}: {message}") from exc


def _load_scan_document(payload: dict, config_path: str | None) -> dict:
    if config_path:
        loaded = _load_document(_resolve_config_path(config_path))
        return loaded

    if "scan" in payload:
        return {"scan": payload.get("scan")}
    return payload


def _find_profile_band(profile: dict, band_name: str):
    bands = profile.get("bands") or []
    for band in bands:
        if str(band.get("name", "")).lower() == str(band_name).lower():
            return band
    return None


def apply_region_profile_to_scan(scan: dict, profile: dict):
    if not isinstance(scan, dict):
        raise ConfigError("scan must be an object")
    if not isinstance(profile, dict):
        raise ConfigError("region profile must be an object")

    band_name = scan.get("band")
    if not band_name:
        return False

    band = _find_profile_band(profile, band_name)
    if not band:
        return False

    start_hz = int(scan.get("start_hz", 0) or 0)
    end_hz = int(scan.get("end_hz", 0) or 0)
    if start_hz <= 0:
        scan["start_hz"] = int(band.get("start_hz", 0))
    if end_hz <= 0:
        scan["end_hz"] = int(band.get("end_hz", 0))
    return True


def load_scan_request(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ConfigError("Scan request payload must be an object")

    config_path = payload.get("scan_config_path")
    loaded = _load_scan_document(payload, config_path)

    _validate_schema(loaded, _SCAN_SCHEMA_PATH, "scan config")

    merged = dict(loaded)
    if payload.get("device"):
        merged["device"] = payload["device"]
    if payload.get("region_profile_path"):
        merged["region_profile_path"] = payload["region_profile_path"]
    return merged


def load_region_profile(config_path: str) -> dict:
    profile = _load_document(_resolve_config_path(config_path))
    _validate_schema(profile, _REGION_SCHEMA_PATH, "region profile")
    return profile
