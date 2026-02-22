<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-02-22 16:27:19 UTC
-->

# Hardware and Performance Requirements

## Target Platforms
- Raspberry Pi 4 (4 GB)
- Raspberry Pi 5 (8 GB)
- PC (dual-core or better)

## SDR Devices
- Primary: RTL-SDR
- Supported: HackRF, Airspy, SDR-capable transceiver (via SoapySDR or vendor API)

## CPU/RAM Guidance
- Raspberry Pi 4: FFT + occupancy + FT8/FT4 + APRS + CW
- Raspberry Pi 5: adds light SSB/ASR with conservative settings
- PC: all decoders with moderate scan rates
- GPU (optional): recommended for stronger ASR models

## Storage
- Minimum 8 GB free for logs, exports, and history
- Optional: SD endurance for continuous logging on Raspberry Pi

## Network
- Local UI access via browser
- Optional remote access requires network hardening

## Time Synchronization
- NTP strongly recommended for FT8/FT4 decode accuracy

## Suggested Scan Parameters
- Step: 2 kHz to 5 kHz (HF), 5 kHz to 25 kHz (VHF/UHF)
- Dwell: 200 to 500 ms
- FFT bins: 1024 to 4096

## Notes
- ASR accuracy is sensitive to noise and RF conditions.
- Downsample/decimate to reduce CPU on Raspberry Pi.
