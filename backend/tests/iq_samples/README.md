<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-02-22 00:34:50 UTC
-->

# IQ samples for test harness

This folder stores IQ fixtures used by the automated harness.

## Current sample

- `cw_reference.json`: deterministic narrow-band pattern used to validate the harness itself.

## Add a real recorded sample

1. Save capture as `.npy` or convert to JSON pattern format used by `cw_reference.json`.
2. Include expected checks in the `expect` section:
   - `min_occupied_segments`
   - `min_peak_snr_db`
   - `mode`
3. Add a corresponding test case in `backend/tests/test_iq_harness.py`.
