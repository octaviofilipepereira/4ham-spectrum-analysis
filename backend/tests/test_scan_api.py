# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

from app.api.scan import _resolve_cw_sweep_bounds


def test_resolve_cw_sweep_bounds_clips_20m_to_cw_segment():
    start_hz, end_hz = _resolve_cw_sweep_bounds("20m", 14_000_000, 14_350_000)

    assert start_hz == 14_000_000
    assert end_hz == 14_070_000