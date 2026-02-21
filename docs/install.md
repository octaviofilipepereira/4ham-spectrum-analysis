# Installation Guide

For a complete, step-by-step manual, see [docs/installation_manual.md](installation_manual.md).
For service deployment/packaging, see [docs/ops_packaging.md](ops_packaging.md).

## Linux (Ubuntu/Debian)
1. Install dependencies: SDR drivers, Python 3.10+, and build tools.
2. Install SoapySDR and RTL-SDR tools plus Python bindings:
	- `sudo apt update`
	- `sudo apt install -y soapysdr-tools libsoapysdr-dev python3-soapysdr`
3. Create a virtual environment and install Python dependencies:
	- `python3 -m venv .venv`
	- `source .venv/bin/activate`
	- `python -m pip install -r backend/requirements.txt`
4. Run backend with uvicorn:
	- `python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000`

## Windows
1. Install SDR drivers (Zadig for RTL-SDR).
2. Install Python 3.10+.
3. Install SoapySDR Windows package or vendor SDK.
4. Run backend with uvicorn and open the UI in the browser:
	- `python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000`

## Raspberry Pi
1. Use 64-bit OS and update packages.
2. Install SoapySDR and RTL-SDR.
3. Reduce sample rate and FFT size for stability.
4. Run backend with uvicorn:
	- `python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000`

## Time Sync
- Enable NTP for FT8/FT4 decoding.

## Notes
- Use a virtual audio cable for WSJT-X integration.
- For APRS, run Direwolf with KISS TCP enabled.
- Optional: set decoder file paths (e.g., `WSJTX_ALLTXT_PATH`) for automatic ingest.
- Optional: enable native WSJT-X UDP ingest with `WSJTX_UDP_ENABLE=1`.
- Optional: enable Direwolf KISS TCP ingest with `DIREWOLF_KISS_ENABLE=1`.
- To auto-start decoder processes at backend startup, install binaries and set:
	- `WSJTX_AUTOSTART=1`, `WSJTX_CMD="wsjtx"`
	- `DIREWOLF_AUTOSTART=1`, `DIREWOLF_CMD="direwolf -t 0 -p"`

### Decoder binaries (Mint/Ubuntu)
```
sudo apt update
sudo apt install -y wsjtx direwolf
```

## Troubleshooting
- If SoapySDR devices are not found, run `SoapySDRUtil --find` to verify driver discovery.
- On Linux, ensure your user has USB access (plugdev/udev rules) for RTL-SDR devices.
- If Python cannot import SoapySDR, confirm `python3-soapysdr` is installed from apt.
