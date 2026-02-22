<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-02-22 16:27:19 UTC
-->

# Changelog

## v0.2.5 - 2026-02-22

### Changed
- Removed Fake waterfall mode from frontend controls and runtime behavior.
- Waterfall now stays in LIVE mode and does not render simulated spectrum data.

### Fixed
- Replaced simulated fallback rendering with a generic user-facing no-data message when no SDR device is available or live frames become stale.
- Improved readability of the waterfall no-data message with larger, centered, high-contrast presentation.

## v0.2.0 - 2026-02-21

### Added
- Configuration loader and schema validation for scan and region profile inputs.
- DSP occupancy improvements with mode heuristics and confidence scoring.
- Decoder pipelines for WSJT-X UDP, Direwolf KISS, CW parsing, and SSB ASR controlled vocabulary.
- WebSocket spectrum streaming backpressure handling and `delta_int8` compressed frames.
- WebGL waterfall rendering with fallback plus JSON/PNG export controls in frontend.
- Persistent export metadata and file rotation workflow in SQLite storage layer.
- IQ-sample QA harness with fixture-driven assertions.
- DSP benchmark tool for cross-platform performance comparison.
- Deployment packaging assets for Linux (`systemd`) and Windows service installation.

### Changed
- Same-origin frontend serving integrated into backend runtime flow.
- Decoder process management supports optional autostart and clean shutdown lifecycle.
- Documentation expanded for installation, operations, storage schema, and websocket contract updates.
- Repository hygiene improved with `.gitignore` for runtime artifacts.

### Fixed
- WSJT-X text parsing now correctly extracts `grid` and `report` from payload tokens.
- Decoder status visibility improved through runtime process state fields.
- Runtime validation paths aligned with current API/event payload behavior.
