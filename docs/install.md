<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-04-21 UTC
-->

# Installation Guide

> **Recommended:** use the automatic graphical installer — just run `./install.sh` from the repository root. It handles everything end-to-end with a guided TUI.
> To remove the installation, run `./uninstall.sh`.

For a complete, step-by-step manual, see [installation_manual.md](installation_manual.md).
For service deployment/packaging, see [ops_packaging.md](ops_packaging.md).

## Automatic Installer (recommended)

```bash
git clone https://github.com/octaviofilipepereira/4ham-spectrum-analysis.git
cd 4ham-spectrum-analysis
./install.sh
```

The installer presents an interactive graphical wizard (whiptail) that:
1. Installs all system packages via `apt`
2. Optionally builds the RTL-SDR Blog v4 driver from source
3. Optionally installs OpenAI Whisper for SSB voice transcription (~700 MB download, asked during setup)
4. Creates the Python virtual environment and installs Python dependencies
5. Asks for an admin username and password (stored securely as bcrypt in the local SQLite database)
6. Installs and starts the systemd background service (auto-start on boot)

On supported Debian-family systems the installer also installs `usbutils`, which provides the `usbreset` utility used by the RTL recovery workflow in Admin Config.

At the end, open the printed URL in your browser and log in. No further steps needed.

Frontend routes after install:
- Main UI: `/`
- Academic analytics dashboard: `/4ham_academic_analytics.html`

---

## Manual Installation

### Linux (Ubuntu 20.04+ / Debian 11+ / Linux Mint 20+ / Raspberry Pi OS 11+)
1. Install dependencies: SDR drivers, Python 3.10+, and build tools.
2. Install SoapySDR and RTL-SDR tools plus Python bindings:
	- `sudo apt update`
	- `sudo apt install -y soapysdr-tools libsoapysdr-dev python3-soapysdr soapysdr-module-rtlsdr rtl-sdr usbutils`
3. **RTL-SDR v4 only** — the standard `rtl-sdr` apt package does not support the RTL-SDR Blog v4. Build the updated driver from source:
	```bash
	sudo apt remove -y rtl-sdr librtlsdr0 librtlsdr-dev
	sudo apt install -y git cmake libusb-1.0-0-dev build-essential
	git clone https://github.com/rtlsdrblog/rtl-sdr-blog
	cd rtl-sdr-blog && mkdir build && cd build
	cmake ../ -DINSTALL_UDEV_RULES=ON
	make && sudo make install && sudo ldconfig
	```
	Blacklist conflicting kernel modules (required for v4):
	```bash
	sudo tee /etc/modprobe.d/blacklist-rtl.conf >/dev/null <<'EOF'
	blacklist dvb_usb_rtl28xxu
	blacklist rtl2832
	blacklist rtl2830
	EOF
	sudo modprobe -r dvb_usb_rtl28xxu 2>/dev/null || true
	```
	Verify: `rtl_test -t`
 	The `usbutils` package also provides `usbreset`, used by the Admin Config RTL recovery workflow.
4. Create a virtual environment and install Python dependencies:
	- `python3 -m venv .venv`
	- `source .venv/bin/activate`
	- `python -m pip install -r backend/requirements.txt`
5. Run backend with uvicorn:
	- `python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000`

## Raspberry Pi
1. Use a 64-bit OS and update packages.
2. Follow the same SDR driver steps as Linux above (including RTL-SDR v4 if applicable).
3. Reduce sample rate and FFT size for stability (see `installation_manual.md`).
4. Run backend with uvicorn:
	- `python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000`

## Time Sync
- Enable NTP for FT8/FT4 decoding.
- Beacon Analysis also depends on reliable UTC timing. If 4ham cannot validate a healthy host time-sync state, Beacon Analysis startup is blocked to avoid false observations.

## Production service (Linux/systemd)
Use the service installer script for end-user production runs:

```bash
chmod +x scripts/install_systemd_service.sh
./scripts/install_systemd_service.sh install
```

Service operations:

```bash
./scripts/install_systemd_service.sh status
./scripts/install_systemd_service.sh stop
./scripts/install_systemd_service.sh restart
./scripts/install_systemd_service.sh logs
./scripts/install_systemd_service.sh uninstall
```

Environment defaults are stored in the project-local `.env` file (at the repository root).

If you only want to remove the service (keeping project files), run:

```bash
./scripts/install_systemd_service.sh uninstall
```

## Server control (runtime)

To start/stop/restart the backend process without systemd (e.g. in dev):

```bash
./scripts/server_control.sh start
./scripts/server_control.sh stop
./scripts/server_control.sh restart
./scripts/server_control.sh status
./scripts/server_control.sh logs
```

### Desktop launcher

On graphical systems, the installer offers a desktop shortcut that opens an interactive terminal menu with Start / Stop / Restart / Open Dashboard options. The launcher can also be run directly:

```bash
./scripts/4ham_launcher.sh
```

## Uninstallation

```bash
./uninstall.sh                                        # safe: removes service, venv, node_modules
./uninstall.sh --purge-data                          # also removes data/, logs/, exports/
./uninstall.sh --purge-system-packages               # also removes system apt packages
./uninstall.sh --purge-all --yes                     # full wipe: everything above + project folder
```

Notes:
- `./uninstall.sh` also removes the project-local `.env` file.
- `./scripts/install_systemd_service.sh uninstall` removes only the service unit (keeps `.env` and project files).

## Notes
- FT8/FT4 decoding uses `jt9` (from WSJT source) directly — no WSJT-X GUI required.
- WSPR decoding uses `wsprd` directly.
- For APRS, run Direwolf with KISS TCP enabled.
- Optional: enable external FT decoder with `FT_EXTERNAL_ENABLE=1`.
- Optional: enable Direwolf KISS TCP ingest with `DIREWOLF_KISS_ENABLE=1`.
- Optional: republish the read-only Academic Analytics dashboard on a public PHP+MySQL host via the built-in push mirror — see [`external_academic_analytics/README.md`](../external_academic_analytics/README.md) and [`docs/external_mirrors.md`](external_mirrors.md). The home backend stays on the LAN; deployment of the receiver is a one-off `rsync` + MySQL schema apply.
- To auto-start Direwolf at backend startup, install the binary and set:
	- `DIREWOLF_AUTOSTART=1`, `DIREWOLF_CMD="direwolf -t 0 -p"`
- **Adding APRS to an existing install:** if you skipped Direwolf during the original installer run, open the web UI → **Admin Config** → tick *Enable APRS packet decoding via Direwolf KISS TCP*. A modal will instruct you to run `sudo bash scripts/enable_aprs.sh` on the server. The helper script is idempotent and does not touch the rest of the installation.
- **SSB Voice Signature (Whisper ASR):** to enable real-time SSB voice transcription after installation, activate the venv and run `pip install openai-whisper`, then enable ASR in Admin → Settings. The `tiny` model is auto-downloaded on first use. Full transcription pipeline requires `ffmpeg` (installed by the auto-installer).

## Waterfall tooltip
- Hovering mode labels (FT8/CW/SSB) in the waterfall shows mode, frequency, callsign, last-seen time, and SNR.
- Callsign resolution order:
	1. nearest frequency match from recent callsign events
	2. fallback to the most recent detected callsign if no local match exists
- If UI behavior looks stale after an update, force reload with `Ctrl+Shift+R`.

### Decoder binaries (Mint/Ubuntu)
```
sudo apt update
sudo apt install -y direwolf
```
Ensure `jt9` and `wsprd` are available in `$PATH` (build from WSJT source or install from package).

## Troubleshooting
- If SoapySDR devices are not found, run `SoapySDRUtil --find` to verify driver discovery.
- On Linux, ensure your user has USB access: add your user to the `plugdev` group (`sudo usermod -aG plugdev $USER`) and reconnect the device.
- If the RTL-SDR v4 is not detected, confirm kernel blacklist is applied and reboot.
- If Python cannot import SoapySDR, confirm `python3-soapysdr` is installed from apt.
