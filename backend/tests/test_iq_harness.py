# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 00:34:50 UTC

from pathlib import Path

from .iq_harness import run_iq_fixture


def test_iq_harness_cw_reference_fixture():
    fixture = Path(__file__).parent / "iq_samples" / "cw_reference.json"
    result = run_iq_fixture(fixture)

    assert result.sample_name == "cw_reference"
    assert result.occupancy_count >= 1
    assert result.best_peak_snr_db >= 5.0
    assert result.mode == "CW"
    assert 0.0 < result.mode_confidence <= 0.95
