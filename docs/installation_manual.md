<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-04-03 UTC
-->

# Installation Manual

This manual provides a complete setup for Linux (Ubuntu/Debian) and Raspberry Pi, including optional decoder integrations.

## Contents
- System Requirements
- Quick Start (graphical installer)
- Service Management (`systemd` helper)
- Prerequisites
- Linux (Ubuntu/Debian)
- Raspberry Pi
- Decoder Integrations
- Verification
- Troubleshooting
- Uninstall

## System Requirements

| Component  | Minimum (no ASR)                                       | With Whisper ASR              |
|------------|--------------------------------------------------------|-------------------------------|
| OS         | Ubuntu 20.04+ / Debian 11+ / Raspberry Pi OS 64-bit    | Same                          |
| CPU        | 2 cores, 1.5 GHz                                       | 4 cores, 2 GHz                |
| RAM        | 2 GB                                                   | 4 GB                          |
| Disk       | 2 GB                                                   | 10 GB (PyTorch/Whisper ~6.8 GB) |
| Python     | 3.10+                                                  | 3.10+                         |
| Time sync  | NTP — required for FT8/FT4 timing                      | NTP required                  |
| SDR        | RTL-SDR, HackRF, Airspy or any SoapySDR device         | Same                          |

> **Measured at v0.8.0**: ~637 MB RSS, ~30% of one CPU core during continuous HF scan.
> **Windows**: partial support via WSL2 only — native Windows is not recommended.

## Prerequisites
- SDR hardware: RTL-SDR (primary), HackRF, Airspy, or SDR transceiver with SoapySDR support.
- Python 3.10+
- Basic build tools (Linux)
- Accurate system time (NTP) for FT8/FT4

## Quick Start (graphical installer)

Since v0.7.1, a guided TUI installer handles the full setup for Linux and Raspberry Pi:

```
git clone https://github.com/octaviofilipepereira/4ham-spectrum-analysis.git
cd 4ham-spectrum-analysis
chmod +x install.sh && ./install.sh
```

The installer covers: system packages, optional RTL-SDR Blog v4 driver build, Python virtual environment, admin account creation (bcrypt-hashed password stored in SQLite), and optional systemd service activation. No manual steps are required after `git clone`.

To remove the installation:
```
./uninstall.sh                           # safe: removes service, venv, node_modules
./uninstall.sh --purge-data             # also removes data/, logs/, exports/
./uninstall.sh --purge-system-packages  # also removes apt packages installed for this app
./uninstall.sh --purge-all --yes        # full wipe
```

Frontend routes after install:
- Main UI: `/`
- Academic analytics dashboard: `/4ham_academic_analytics.html`

## Service Management (`systemd` helper)

For production-style service management, use:

```
./scripts/install_systemd_service.sh install
./scripts/install_systemd_service.sh status
./scripts/install_systemd_service.sh logs
./scripts/install_systemd_service.sh restart
./scripts/install_systemd_service.sh stop
./scripts/install_systemd_service.sh uninstall
```

Environment defaults are stored in the project-local `.env` file (at the repository root).

Note:
- `install_systemd_service.sh uninstall` removes only the service unit.
- `./uninstall.sh` removes service + local environments and also removes the `.env` file.

For manual or customised setups, follow the sections below.

## Linux (Ubuntu/Debian)

### 1) System dependencies
```
sudo apt update
sudo apt install -y soapysdr-tools libsoapysdr-dev python3-soapysdr soapysdr-module-rtlsdr rtl-sdr
```

Optional utilities:
```
sudo apt install -y git python3-venv build-essential
```

### 2) USB permissions
Add your user to the `plugdev` group so the device is accessible without root:
```
sudo usermod -aG plugdev $USER
```
Log out and back in for the group change to take effect.

If udev rules are needed (older systems), add them manually:
```
sudo tee /etc/udev/rules.d/20-rtl-sdr.rules >/dev/null <<'EOF'
SUBSYSTEM=="usb", ATTR{idVendor}=="0bda", ATTR{idProduct}=="2838", MODE:="0666"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### 2a) RTL-SDR v4 — updated driver (required for RTL-SDR Blog v4 only)

The standard `rtl-sdr` apt package does not support the RTL-SDR Blog v4 dongle.
If you have a v4, remove the system package and build the updated driver:

```
sudo apt remove -y rtl-sdr librtlsdr0 librtlsdr-dev
sudo apt install -y cmake libusb-1.0-0-dev build-essential
git clone https://github.com/rtlsdrblog/rtl-sdr-blog
cd rtl-sdr-blog && mkdir build && cd build
cmake ../ -DINSTALL_UDEV_RULES=ON
make && sudo make install && sudo ldconfig
```

Blacklist conflicting kernel modules (required — otherwise the kernel claims the device before the driver can):
```
sudo tee /etc/modprobe.d/blacklist-rtl.conf >/dev/null <<'EOF'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
EOF
sudo modprobe -r dvb_usb_rtl28xxu 2>/dev/null || true
```

Reconnect the dongle and verify:
```
rtl_test -t
SoapySDRUtil --find
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
python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

### 5) Open the UI
Open the backend-served UI in your browser:
- `http://localhost:8000/`

## Raspberry Pi

### 1) OS and packages
Use a 64-bit OS (Raspberry Pi OS 64-bit recommended), then install dependencies:
```
sudo apt update
sudo apt install -y soapysdr-tools libsoapysdr-dev python3-soapysdr soapysdr-module-rtlsdr rtl-sdr
```

**RTL-SDR v4 only** — follow section 2a from the Linux section above (build from `rtlsdrblog/rtl-sdr-blog` source and apply kernel blacklist). The process is identical on Raspberry Pi.

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

### SSB ASR / Whisper (optional)
As of v0.8.0, real-time SSB voice demodulation and Whisper ASR are fully integrated. SSB transmissions now appear as **Voice Confirmed** (no transcript), **Voice Transcript** (with Whisper text), or with the **resolved callsign** when one is detected.

**Installation (if skipped during `./install.sh`):**
```
source .venv/bin/activate
# x86_64 — CPU-only PyTorch to avoid the 915 MB CUDA build:
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install openai-whisper
```
The `tiny` Whisper model (~75 MB) is auto-downloaded on first use. The `base` model is also supported and offers better accuracy.

**Requirements:**
- `ffmpeg` must be installed (included by the auto-installer: `sudo apt install -y ffmpeg`)
- Minimum ~1 GB free disk for model cache, ~500 MB RAM at runtime (tiny)
- On Raspberry Pi 4/5: supported but expect ~2–4 s transcription latency per segment

**Enable in Admin panel:**
1. Open the web UI and log in.
2. Go to **Admin** → **Settings**.
3. Enable **SSB ASR** and select the Whisper model (`tiny` recommended for low-power hardware).

**Audio source:**
By default, ASR uses the audio demodulated from the RTL-SDR IQ stream. For higher quality, use a hardware transceiver (Yaesu FT-991A, ICOM IC-7300) connected via USB audio. The transceiver's built-in sound card provides better receiver front-end sensitivity and filtering than an RTL-SDR on busy HF bands.

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

WSJT-X GUI configuration (required for FT8/FT4 callsign ingest):

1. Open WSJT-X and go to `File` -> `Settings` (or press `F2`).
2. Open the `Reporting` tab.
3. Set `UDP Server` to `127.0.0.1`.
4. Set `UDP Server Port Number` to `2237`.
5. Enable `Accept UDP requests`.
6. Keep WSJT-X decoding on an active FT8/FT4 frequency.

Without this WSJT-X Reporting configuration, the platform can still show RF occupancy in scan/waterfall, but callsigns from FT8/FT4 will not be ingested.

### Direwolf KISS TCP
The backend can connect to Direwolf KISS TCP and ingest APRS frames automatically. Configure:

- `DIREWOLF_KISS_ENABLE`: set to `1` to enable
- `DIREWOLF_KISS_HOST`: host (default `127.0.0.1`)
- `DIREWOLF_KISS_PORT`: TCP port (default `8001`)

### Decoder process auto-start
To auto-start WSJT-X and Direwolf when the backend starts:

- `WSJTX_AUTOSTART=1`
- `WSJTX_CMD="wsjtx"` (or absolute path to executable)
- `DIREWOLF_AUTOSTART=1`
- `DIREWOLF_CMD="direwolf -t 0 -p"` (or absolute path and options)

Linux package installation example (Mint/Ubuntu):

```
sudo apt update
sudo apt install -y wsjtx direwolf
```

Quick verify:

```
command -v wsjtx
command -v direwolf
```

If binaries are not in `PATH`, use absolute commands, e.g.:

```
WSJTX_CMD="/usr/bin/wsjtx"
DIREWOLF_CMD="/usr/bin/direwolf -t 0 -p"
```

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

### Waterfall tooltip (mode labels)
- Open the web UI and ensure scan is running so mode labels (e.g., FT8/CW/SSB) appear over the waterfall.
- Hover a mode label to see tooltip details:
  - mode
  - frequency (MHz)
  - callsign
  - last seen time
  - SNR
- Callsign resolution policy:
  - first: nearest-frequency match from recent callsign events
  - fallback: most recently detected callsign when no local frequency match exists
- If the browser still shows stale tooltip behavior after updates, do a hard refresh (`Ctrl+Shift+R`).

## Troubleshooting
- If SoapySDR devices are not found, verify drivers and run `SoapySDRUtil --find`.
- If Python cannot import SoapySDR, confirm `python3-soapysdr` is installed on Linux.
- If no FFT frames appear, reduce sample rate or close other SDR applications.
- For RTL-SDR permissions, confirm `plugdev` group membership (`groups $USER`) and reconnect the device.
- If the RTL-SDR v4 is not detected after building from source, confirm the kernel blacklist is in place (`cat /etc/modprobe.d/blacklist-rtl.conf`) and reboot.
- If scan is running and RF is visible but no callsigns appear, confirm WSJT-X `Reporting` is set to `127.0.0.1:2237` and that `/api/decoders/status` updates `wsjtx_udp.last_packet_at`.

## Uninstall

Recommended:

```
./uninstall.sh
./uninstall.sh --purge-data
./uninstall.sh --purge-system-packages
./uninstall.sh --purge-all --yes
```

Service-only uninstall:

```
./scripts/install_systemd_service.sh uninstall
```
