<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-02-22 16:27:19 UTC
-->

# Technical Backlog

## Foundation
- [x] Define config loader and validation (YAML + JSON Schema)
- [x] Implement device abstraction layer (SoapySDR first)
- [x] Create scan scheduler (band profiles, step, dwell)

## DSP Pipeline
- [x] FFT pipeline with noise floor estimation
- [x] Peak detection and occupancy classification
- [x] Mode heuristics (AM/FM/SSB/FSK/PSK)

## Decoders
- [x] WSJT-X integration (FT8/FT4)
- [x] Direwolf integration (APRS)
- [x] CW decoder pipeline
- [x] SSB ASR pipeline with controlled vocabulary
- [ ] Internal FT8/FT4 decoder migration (remove WSJT-X runtime dependency)

## API and Streaming
- [x] REST endpoints (OpenAPI driven)
- [x] WebSocket server with backpressure
- [x] Spectrum frame compression (delta_int8)

## UI
- [x] Waterfall rendering (WebGL)
- [x] Scan control panel and presets
- [x] Event list and filters
- [x] Export UI for CSV/JSON/PNG

## Storage
- [x] SQLite schema for events and occupancy
- [x] Exporters and rotation policies

## QA and Ops
- [x] Test harness with recorded IQ samples
- [x] Performance benchmarks per platform
- [x] Packaging: Linux (systemd) and Windows service
