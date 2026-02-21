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

## API and Streaming
- REST endpoints (OpenAPI driven)
- WebSocket server with backpressure
- Spectrum frame compression (delta_int8)

## UI
- Waterfall rendering (WebGL)
- Scan control panel and presets
- Event list and filters
- Export UI for CSV/JSON/PNG

## Storage
- SQLite schema for events and occupancy
- Exporters and rotation policies

## QA and Ops
- Test harness with recorded IQ samples
- Performance benchmarks per platform
- Packaging: Linux (systemd) and Windows service
