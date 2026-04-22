# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
"""
Features API
============

Public, unauthenticated endpoint exposing high-level feature flags to the
frontend. The frontend reads this once on boot to decide whether to render
optional UI surfaces (e.g. LoRa-APRS controls).

No secrets are leaked: only boolean flags whose defaults are documented in
``app.core.features``.
"""

from typing import Dict

from fastapi import APIRouter

from app.core import features


router = APIRouter()


@router.get("")
def get_features() -> Dict[str, bool]:
    """Return current feature-flag state.

    Public — used at frontend boot to render or hide optional UI sections.
    """
    return features.features_snapshot()
