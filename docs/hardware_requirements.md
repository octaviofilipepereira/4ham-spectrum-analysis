<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-03-24 UTC
-->

# Hardware and Performance Requirements

## Operating System
- **Linux** (Debian 11+ / Ubuntu 22.04+ / Raspberry Pi OS Bookworm) — primary and recommended.
- **Windows 10/11**: supported via WSL2 or native Python; SoapySDR driver support varies.
- **Python**: 3.10 or later.

## Target Platforms
- Raspberry Pi 4 (4 GB RAM) — minimum viable.
- Raspberry Pi 5 (8 GB RAM) — recommended for SBC deployments.
- PC (dual-core or better, 4 GB+ RAM).

## SDR Devices
- **Primary**: RTL-SDR Blog v3 / v4 (via SoapySDR).
- **Supported**: HackRF, Airspy, any SoapySDR-compatible device.
- **Planned**: transceiver SDR interfaces (FT-991A, IC-7300 via CAT/audio).
- 1 x USB 2.0 port required.

## Minimum Hardware by Scenario

| | **Without ASR** | **With Whisper ASR** |
|---|---|---|
| **CPU** | 2 cores (RPi 4 or x86) | 4 cores x86 |
| **RAM** | 2 GB | 4 GB |
| **Disk** | 2 GB free | 10 GB free |

## CPU/RAM Guidance
- **Raspberry Pi 4 (4 GB)**: scan + FFT + FT8/FT4 + APRS + CW — no Whisper ASR.
- **Raspberry Pi 5 (8 GB)**: adds light Whisper ASR (tiny/base model, CPU only).
- **PC (4+ cores, 4 GB+)**: all decoders including Whisper at moderate scan rates.
- **GPU PC**: Whisper medium/large models for better noise/accent handling.

## Measured Resource Usage (v0.8.0, active scan)
- **RAM (RSS)**: ~640 MB with scan + FFT + decoders running.
- **CPU**: ~30% of one core during continuous HF scan.
- **Database**: ~5 MB at 25k events.

## Storage
- Python venv (without Whisper): ~500 MB.
- Python venv (with Whisper + PyTorch/CUDA): ~7.3 GB.
- SQLite database at 500k events (configured limit): ~100 MB.
- Logs with rotation (10 MB x 5 backups): ~50 MB max.
- IQ recording (configurable limit): up to 512 MB.
- **Minimum free**: 2 GB without ASR, 10 GB with Whisper.
- Optional: SD endurance for continuous logging on Raspberry Pi.

## Network
- Local UI access via browser (default: `http://localhost:8000`).
- Optional remote access requires network hardening (see [security.md](security.md)).

## Time Synchronization
- **NTP strongly recommended** for FT8/FT4 decode accuracy (timing-critical modes).

## Suggested Scan Parameters
- Step: 2 kHz to 5 kHz (HF), 5 kHz to 25 kHz (VHF/UHF).
- Dwell: 200 to 500 ms.
- FFT bins: 1024 to 4096.

## Performance Tips
- Raspberry Pi: limit sample rate, batch FFT processing.
- Use compression/downsampling for efficient WebSocket streaming.
- Disable Whisper ASR on memory-constrained systems to save ~1.5 GB RAM.
- Stop unnecessary system services (databases, IDEs) on dedicated stations.
- ASR accuracy is sensitive to noise and RF conditions.
- Downsample/decimate to reduce CPU on Raspberry Pi.
