# Installation Manual

This manual provides a complete setup for Linux, Windows, and Raspberry Pi, including optional decoder integrations.

## Contents
- Prerequisites
- Linux (Ubuntu/Debian)
- Windows
- Raspberry Pi
- Decoder Integrations
- Verification
- Troubleshooting
- Uninstall

## Prerequisites
- SDR hardware: RTL-SDR (primary), HackRF, Airspy, or SDR transceiver with SoapySDR support.
- Python 3.10+
- Basic build tools (Linux)
- Accurate system time (NTP) for FT8/FT4

## Linux (Ubuntu/Debian)

### 1) System dependencies
```
sudo apt update
sudo apt install -y soapysdr-tools libsoapysdr-dev python3-soapysdr rtl-sdr
```

Optional utilities:
```
sudo apt install -y git python3-venv build-essential
```

### 2) USB permissions
If RTL-SDR requires root access, add udev rules (example):
```
sudo tee /etc/udev/rules.d/20-rtl-sdr.rules >/dev/null <<'EOF'
SUBSYSTEM=="usb", ATTR{idVendor}=="0bda", ATTR{idProduct}=="2838", MODE:="0666"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### 3) Python environment
From the repo root:
```
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
```

### 4) Run backend
```
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

### 5) Open the UI
Open the static frontend in your browser:
- Open [frontend/index.html](../frontend/index.html)
- Or serve it with any static server of your choice.

## Windows

### 1) SDR drivers
- Install Zadig and replace the RTL-SDR driver with WinUSB.
- For HackRF/Airspy, install the vendor SDKs.

### 2) SoapySDR
- Install SoapySDR for Windows, or use the vendor SDK if it includes Soapy support.
- Validate device discovery with SoapySDRUtil (if available).

### 3) Python environment
```
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r backend\requirements.txt
```

### 4) Run backend
```
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

### 5) Open the UI
Open [frontend/index.html](../frontend/index.html) in your browser.

## Raspberry Pi

### 1) OS and packages
Use a 64-bit OS, then install dependencies:
```
sudo apt update
sudo apt install -y soapysdr-tools libsoapysdr-dev python3-soapysdr rtl-sdr
```

### 2) Python environment
```
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
```

### 3) Performance tuning
- Lower sample rate (e.g., 48 kHz to 240 kHz)
- Reduce FFT size if CPU usage is high

## Decoder Integrations

### File watchers (automatic ingest)
The backend can tail decoder output files and ingest callsigns automatically. Configure paths via environment variables before starting the backend:

- `WSJTX_ALLTXT_PATH`: path to WSJT-X `ALL.TXT`
- `DIREWOLF_LOG_PATH`: path to Direwolf log/decoded output
- `CW_DECODE_PATH`: path to a text file with decoded CW lines
- `DECODER_TAIL_FROM_START`: set to `1` to start from beginning; default starts at end

### WSJT-X UDP (native protocol)
The backend can listen to WSJT-X UDP broadcast packets (native protocol). Configure:

- `WSJTX_UDP_ENABLE`: set to `1` to enable listener
- `WSJTX_UDP_HOST`: bind address (default `0.0.0.0`)
- `WSJTX_UDP_PORT`: UDP port (default `2237`)

### Direwolf KISS TCP
The backend can connect to Direwolf KISS TCP and ingest APRS frames automatically. Configure:

- `DIREWOLF_KISS_ENABLE`: set to `1` to enable
- `DIREWOLF_KISS_HOST`: host (default `127.0.0.1`)
- `DIREWOLF_KISS_PORT`: TCP port (default `8001`)

## DSP Tuning
Optional environment variables to refine DSP behavior:

- `DSP_AGC_ENABLE`: set to `1` to enable AGC
- `DSP_AGC_TARGET_RMS`: target RMS level (default `0.25`)
- `DSP_AGC_MAX_GAIN_DB`: max AGC gain in dB (default `30`)
- `DSP_AGC_ALPHA`: smoothing factor for gain (default `0.2`)
- `DSP_SNR_THRESHOLD_DB`: SNR threshold for occupancy (default `6`)
- `DSP_MIN_BW_HZ`: minimum occupancy bandwidth (default `500`)

### WSJT-X (FT8/FT4)
- Configure WSJT-X to write decoded messages to ALL.TXT.
- Use the decoder ingest endpoint:
```
curl -X POST http://localhost:8000/api/decoders/wsjtx \
  -H "Content-Type: application/json" \
  -d '{"line": "200109  -12  0.2  14074000  CT1ABC EA1XYZ IO81"}'
```

### Direwolf (APRS)
- Run Direwolf with KISS TCP enabled.
- Send decoded text frames to the APRS endpoint:
```
curl -X POST http://localhost:8000/api/decoders/aprs \
  -H "Content-Type: application/json" \
  -d '{"line": "CT1ABC>APRS,CPNW2*:!3859.50N/00911.20W-Test"}'
```

### CW
- If you have decoded Morse text, send it to the CW endpoint:
```
curl -X POST http://localhost:8000/api/decoders/cw \
  -H "Content-Type: application/json" \
  -d '{"text": "CQ CQ CT1ABC"}'
```

## Verification

### Device discovery
```
SoapySDRUtil --find
```

### Backend health
```
curl http://localhost:8000/api/health
```

### Scan start/stop
```
python backend/cli.py --start --band 20m --start-hz 14000000 --end-hz 14350000
python backend/cli.py --stop
```

## Troubleshooting
- If SoapySDR devices are not found, verify drivers and run `SoapySDRUtil --find`.
- If Python cannot import SoapySDR, confirm `python3-soapysdr` is installed on Linux.
- If no FFT frames appear, reduce sample rate or close other SDR applications.
- For RTL-SDR permissions, confirm udev rules and reconnect the device.

## Uninstall
- Remove the virtual environment: `rm -rf .venv`
- Remove system packages (Linux):
```
sudo apt remove soapysdr-tools libsoapysdr-dev python3-soapysdr rtl-sdr
```
