# WebSocket Specification

## Overview
This document defines WebSocket channels, message envelopes, and payloads for real-time data.

## Channels
- `/ws/spectrum`: FFT and waterfall frames
- `/ws/events`: occupancy and callsign events
- `/ws/status`: scan and system status

## Message Envelope
All messages use a single root object with one top-level key:
- `spectrum_frame`
- `event`
- `status`
- `error`

## Spectrum Frames
### Raw frame
```json
{
  "spectrum_frame": {
    "timestamp": "2026-02-20T12:34:56Z",
    "center_hz": 14074000,
    "span_hz": 3000,
    "bin_hz": 3.9,
    "fft_db": [-120.1, -118.2, -116.7]
  }
}
```

### Compressed frame
```json
{
  "spectrum_frame": {
    "timestamp": "2026-02-20T12:34:56Z",
    "center_hz": 7074000,
    "span_hz": 3000,
    "bin_hz": 3.9,
    "encoding": "delta_int8",
    "fft_ref_db": -120.0,
    "fft_step_db": 0.5,
    "fft_delta": [0, 1, 0, -1]
  }
}
```

## Events
Events use the schema in [events.schema.json](../events.schema.json).

```json
{
  "event": {
    "type": "callsign",
    "timestamp": "2026-02-20T12:34:56Z",
    "band": "20m",
    "frequency_hz": 14074000,
    "mode": "FT8",
    "callsign": "CT1ABC",
    "confidence": 0.94,
    "source": "wsjtx",
    "device": "rtl_sdr"
  }
}
```

## Status
```json
{
  "status": {
    "state": "running",
    "device": "rtl_sdr",
    "cpu_pct": 62.5,
    "drop_rate_pct": 0.4
  }
}
```

## Rate Guidelines
- Spectrum frames: 5 to 15 fps (configurable)
- Events: real time (target < 500 ms latency)
- Status: 1 to 2 Hz

## Backpressure and Drop Policy
- If client is slow, drop oldest spectrum frames first.
- Events must not be dropped; if necessary, batch in one message.

## Error Message
```json
{
  "error": {
    "code": "scan_not_running",
    "message": "Scan is not active"
  }
}
```

## Versioning
- Add `protocol_version` in the status payload when breaking changes are introduced.
