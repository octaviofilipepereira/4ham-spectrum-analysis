# Installation Guide

For a complete, step-by-step manual, see [docs/installation_manual.md](installation_manual.md).

## Linux (Ubuntu/Debian)
1. Install dependencies: SDR drivers, Python 3.10+, and build tools.
2. Install SoapySDR and RTL-SDR tools plus Python bindings:
	- `sudo apt update`
	- `sudo apt install -y soapysdr-tools libsoapysdr-dev python3-soapysdr`
3. Create a virtualenv and install Python deps:
	- `python3 -m venv .venv`
	- `source .venv/bin/activate`
	- `python -m pip install -r backend/requirements.txt`
4. Run backend with uvicorn.

## Windows
1. Install SDR drivers (Zadig for RTL-SDR).
2. Install Python 3.10+.
3. Install SoapySDR Windows package or vendor SDK.
4. Run backend with uvicorn and open the UI in browser.

## Raspberry Pi
1. Use 64-bit OS and update packages.
2. Install SoapySDR and RTL-SDR.
3. Reduce sample rate and FFT size for stability.

## Time Sync
- Enable NTP for FT8/FT4 decoding.

## Notes
- Use a virtual audio cable for WSJT-X integration.
- For APRS, run Direwolf with KISS TCP enabled.
- Optional: set decoder file paths (e.g., `WSJTX_ALLTXT_PATH`) for automatic ingest.
- Optional: enable native WSJT-X UDP ingest with `WSJTX_UDP_ENABLE=1`.
- Optional: enable Direwolf KISS TCP ingest with `DIREWOLF_KISS_ENABLE=1`.

## Troubleshooting
- If SoapySDR devices are not found, run `SoapySDRUtil --find` to verify driver discovery.
- On Linux, ensure your user has USB access (plugdev/udev rules) for RTL-SDR devices.
- If Python cannot import SoapySDR, confirm `python3-soapysdr` is installed from apt.
