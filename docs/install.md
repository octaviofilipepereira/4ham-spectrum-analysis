# Installation Guide

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
