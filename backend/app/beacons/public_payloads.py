"""Public Beacon payload shaping for REST and WebSocket surfaces."""

from __future__ import annotations

from typing import Any, Mapping

_OBSERVATION_INTERNAL_KEYS = frozenset({"id_confirmed", "id_confidence", "drift_ms"})
_HEATMAP_INTERNAL_KEYS = frozenset({"id_confirmed", "best_id_confirmed"})


def _without_keys(row: Mapping[str, Any] | None, keys: frozenset[str]) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: value for key, value in row.items() if key not in keys}


def public_beacon_observation(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return the public Beacon observation shape without internal diagnostics."""
    return _without_keys(row, _OBSERVATION_INTERNAL_KEYS)


def public_beacon_heatmap_cell(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return the public Beacon heatmap cell without internal confirmation fields."""
    return _without_keys(row, _HEATMAP_INTERNAL_KEYS)