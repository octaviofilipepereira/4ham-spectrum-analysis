# Technical Backlog

## Foundation
- Define config loader and validation (YAML + JSON Schema)
- Implement device abstraction layer (SoapySDR first)
- Create scan scheduler (band profiles, step, dwell)

## DSP Pipeline
- FFT pipeline with noise floor estimation
- Peak detection and occupancy classification
- Mode heuristics (AM/FM/SSB/FSK/PSK)

## Decoders
- WSJT-X integration (FT8/FT4)
- Direwolf integration (APRS)
- CW decoder pipeline
- SSB ASR pipeline with controlled vocabulary

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
