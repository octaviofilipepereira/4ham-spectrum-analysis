# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
"""
Feature Flags
=============

Single source of truth for high-level feature toggles that gate entire
subsystems. Flags are read from environment variables on each call so that
tests and ``.env`` updates can flip them without re-importing the module.

Currently defined flags:

* ``FEATURE_LORA_APRS`` — controls visibility of the LoRa-APRS subsystem
  (UDP listener auto-start, settings exposure, frontend UI elements).
  Default: ``false``. Set to ``true`` (or ``1`` / ``yes`` / ``on``) to enable.

Why a flag (rather than removing the code)?
-------------------------------------------
The LoRa-APRS pipeline depends on an external GNU Radio flowgraph
(``gr-lora_sdr``) and dedicated SDR hardware that the default install
does not assume. Hiding the feature behind a single flag keeps the code
fully reversible (no DB migrations, no destructive removal) while giving
the default user a clean UI without dead-end controls.
"""

from __future__ import annotations

import os


_TRUTHY = {"1", "true", "yes", "on"}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUTHY


def lora_aprs_enabled() -> bool:
    """Return ``True`` when the LoRa-APRS subsystem should be exposed."""
    return _env_flag("FEATURE_LORA_APRS", default=False)


def features_snapshot() -> dict:
    """Return a JSON-serialisable snapshot of all public feature flags."""
    return {
        "lora_aprs": lora_aprs_enabled(),
    }
