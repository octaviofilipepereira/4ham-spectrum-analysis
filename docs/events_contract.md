<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-02-22 00:34:50 UTC
-->

# Events Contract by Mode

This document defines mode-specific fields for event payloads.
All events must also satisfy the base schema in [events.schema.json](../events.schema.json).

## Common Fields
- type: occupancy | callsign
- timestamp: ISO-8601
- band, frequency_hz, mode, snr_db, confidence, source, device
- scan_id (optional)

## FT8 / FT4
- type: callsign
- mode: FT8 or FT4
- df_hz: integer
- raw: decoded line from WSJT-X
- optional: grid, report, time_s, dt_s, is_new

Example
```json
{
  "type": "callsign",
  "timestamp": "2026-02-20T12:34:56Z",
  "band": "20m",
  "frequency_hz": 14074000,
  "mode": "FT8",
  "callsign": "CT1ABC",
  "snr_db": -12.5,
  "df_hz": 42,
  "raw": "CT1ABC EA1XYZ IO81",
  "confidence": 0.94,
  "source": "wsjtx",
  "device": "rtl_sdr"
}
```

## APRS
- type: callsign
- mode: APRS
- raw: AX.25 payload
- optional: path, payload, lat, lon, msg

Example
```json
{
  "type": "callsign",
  "timestamp": "2026-02-20T12:34:56Z",
  "band": "2m",
  "frequency_hz": 144800000,
  "mode": "APRS",
  "callsign": "CT1ABC",
  "raw": "CT1ABC>APRS,CPNW2*:!3859.50N/00911.20W-Test",
  "confidence": 0.98,
  "source": "direwolf",
  "device": "rtl_sdr"
}
```

## CW
- type: callsign
- mode: CW
- raw: decoded morse text
- optional: wpm

Example
```json
{
  "type": "callsign",
  "timestamp": "2026-02-20T12:34:56Z",
  "band": "40m",
  "frequency_hz": 7025000,
  "mode": "CW",
  "callsign": "CT1ABC",
  "raw": "CQ CQ CT1ABC",
  "confidence": 0.72,
  "source": "cw",
  "device": "rtl_sdr"
}
```

## SSB (Voice)
- type: callsign
- mode: SSB
- raw: ASR transcription
- optional: asr_score

Example
```json
{
  "type": "callsign",
  "timestamp": "2026-02-20T12:34:56Z",
  "band": "20m",
  "frequency_hz": 14250000,
  "mode": "SSB",
  "callsign": "CT1ABC",
  "raw": "cq cq this is charlie tango one alpha bravo charlie",
  "confidence": 0.41,
  "source": "asr",
  "device": "rtl_sdr"
}
```

## Occupancy
- type: occupancy
- bandwidth_hz, power_dbm, threshold_dbm, occupied
- optional: offset_hz, snr_db, noise_floor_db

Example
```json
{
  "type": "occupancy",
  "timestamp": "2026-02-20T12:34:56Z",
  "band": "40m",
  "frequency_hz": 7074000,
  "bandwidth_hz": 2700,
  "power_dbm": -92.3,
  "snr_db": 6.1,
  "threshold_dbm": -98.0,
  "occupied": true,
  "mode": "SSB",
  "confidence": 0.62,
  "device": "rtl_sdr"
}
```
