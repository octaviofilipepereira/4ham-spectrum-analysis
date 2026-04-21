#!/usr/bin/env bash
# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
#
# 4ham-spectrum-analysis — Graphical Installer (whiptail TUI)
#
# Usage:
#   chmod +x install.sh
#   ./install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR"
SERVICE_NAME="4ham-spectrum-analysis"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
ENV_FILE="$ROOT_DIR/.env"
LOG_FILE="/tmp/4ham-install-$(date +%Y%m%d-%H%M%S).log"
BT="4ham-spectrum-analysis — Installer"

FIFO=""
GAUGE_PID=""
declare -a _TMPFILES=()

run_sudo() { [[ "${EUID}" -eq 0 ]] && "$@" || sudo "$@"; }

version_ge() {
  local current="$1"
  local minimum="$2"
  [[ "$(printf '%s\n%s\n' "$minimum" "$current" | sort -V | head -n1)" == "$minimum" ]]
}

OS_ID=""
OS_VERSION_ID=""
OS_PRETTY_NAME=""

detect_linux_compatibility() {
  if [[ ! -f /etc/os-release ]]; then
    echo "Unsupported Linux distribution: missing /etc/os-release" >&2
    return 1
  fi

  # shellcheck disable=SC1091
  source /etc/os-release

  OS_ID="${ID:-unknown}"
  OS_VERSION_ID="${VERSION_ID:-0}"
  OS_PRETTY_NAME="${PRETTY_NAME:-$OS_ID}"

  local id_lower="${OS_ID,,}"
  case "$id_lower" in
    ubuntu)
      version_ge "$OS_VERSION_ID" "20.04"
      return
      ;;
    debian)
      version_ge "$OS_VERSION_ID" "11"
      return
      ;;
    linuxmint)
      version_ge "$OS_VERSION_ID" "20"
      return
      ;;
    raspbian)
      version_ge "$OS_VERSION_ID" "11"
      return
      ;;
    *)
      return 1
      ;;
  esac
}

validate_runtime_dependencies() {
  local -a missing_cmds=()
  local -a required_cmds=(
    SoapySDRUtil
    rtl_test
    ffmpeg
    jt9
    wsprd
    node
    npm
  )

  # Direwolf is optional — only validate if APRS was selected
  if [[ ${_install_direwolf:-0} -eq 1 ]]; then
    required_cmds+=(direwolf)
  fi

  for cmd in "${required_cmds[@]}"; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      missing_cmds+=("$cmd")
    fi
  done

  if ! "$PYTHON_BIN" -c "import SoapySDR" >/dev/null 2>&1; then
    missing_cmds+=("python:SoapySDR")
  fi

  if [[ ${#missing_cmds[@]} -gt 0 ]]; then
    printf '%s\n' "${missing_cmds[@]}" | paste -sd ', ' -
    return 1
  fi

  return 0
}

# ── cleanup on exit ────────────────────────────────────────────────────────────
cleanup() {
  exec 3>&- 2>/dev/null || true
  [[ -n "${GAUGE_PID:-}" ]] && kill "${GAUGE_PID}" 2>/dev/null || true
  [[ -n "${FIFO:-}"      ]] && rm -f "${FIFO}"    2>/dev/null || true
  if [[ ${#_TMPFILES[@]} -gt 0 ]]; then
    for _f in "${_TMPFILES[@]}"; do rm -f "$_f" 2>/dev/null || true; done
  fi
}
trap cleanup EXIT

# ── progress gauge helpers ─────────────────────────────────────────────────────
start_gauge() {
  FIFO="$(mktemp -u /tmp/4ham-gauge-XXXXXX)"
  mkfifo "$FIFO"
  whiptail --backtitle "$BT" --gauge "$1" 8 72 0 < "$FIFO" &
  GAUGE_PID=$!
  exec 3>"$FIFO"
}

gauge_step() {
  printf 'XXX\n%d\n%s\n\nSee log: %s\nXXX\n' "$1" "$2" "$LOG_FILE" >&3 2>/dev/null || true
}

close_gauge() {
  printf 'XXX\n100\nComplete.\nXXX\n' >&3 2>/dev/null || true
  exec 3>&- 2>/dev/null || true
  wait "${GAUGE_PID}" 2>/dev/null || true
  rm -f "${FIFO}"; FIFO=""; GAUGE_PID=""
}

abort() {
  exec 3>&- 2>/dev/null || true
  if [[ -n "${GAUGE_PID:-}" ]]; then
    kill "${GAUGE_PID}" 2>/dev/null || true
    wait "${GAUGE_PID}" 2>/dev/null || true
    GAUGE_PID=""
  fi
  [[ -n "${FIFO:-}" ]] && { rm -f "${FIFO}"; FIFO=""; }
  whiptail --backtitle "$BT" --title "Installation Failed" \
    --msgbox "Error during installation.\n\nDetail: $1\n\nFull log:\n  $LOG_FILE" 13 70
  exit 1
}

# ── sanity checks ──────────────────────────────────────────────────────────────
if [[ "${EUID}" -eq 0 ]]; then
  if command -v whiptail &>/dev/null; then
    whiptail --backtitle "$BT" --title "Error" \
      --msgbox "Do not run this installer as root.\n\nRun as a normal user with sudo access:\n\n  ./install.sh" 11 62
  else
    echo "Do not run this installer as root."
    echo "Run as a normal user with sudo access: ./install.sh"
  fi
  exit 1
fi

if ! command -v apt-get &>/dev/null; then
  if command -v whiptail &>/dev/null; then
    whiptail --backtitle "$BT" --title "Unsupported OS" \
      --msgbox "This installer requires apt.\nSupported: Ubuntu, Debian, Linux Mint, Raspberry Pi OS." 9 66
  else
    echo "Unsupported OS: this installer requires apt."
    echo "Supported: Ubuntu, Debian, Linux Mint, Raspberry Pi OS."
  fi
  exit 1
fi

if ! detect_linux_compatibility; then
  local_msg="Detected Linux: ${OS_PRETTY_NAME:-unknown} (version ${OS_VERSION_ID:-unknown})\n\n"
  local_msg+="Minimum supported versions:\n"
  local_msg+="- Ubuntu 20.04+\n"
  local_msg+="- Debian 11+\n"
  local_msg+="- Linux Mint 20+\n"
  local_msg+="- Raspberry Pi OS (Raspbian) 11+\n\n"
  local_msg+="This installer cannot continue on the detected system."
  if command -v whiptail &>/dev/null; then
    whiptail --backtitle "$BT" --title "Unsupported Linux Version" --msgbox "$local_msg" 16 72
  else
    printf '%b\n' "$local_msg"
  fi
  exit 1
fi

# ── ensure whiptail is available ───────────────────────────────────────────────
if ! command -v whiptail &>/dev/null; then
  echo "Installing whiptail for graphical interface..."
  run_sudo apt-get update -qq
  run_sudo apt-get install -y whiptail
fi

if ! command -v python3 &>/dev/null; then
  whiptail --backtitle "$BT" --title "Error" \
    --msgbox "python3 not found.\nInstall it first: sudo apt install python3" 9 58
  exit 1
fi

_pyok=$(python3 -c "import sys; print('ok' if sys.version_info>=(3,10) else 'old')" 2>/dev/null || echo old)
if [[ "$_pyok" != "ok" ]]; then
  whiptail --backtitle "$BT" --title "Python Version" \
    --msgbox "Python 3.10 or later is required.\nFound: $(python3 --version 2>&1)" 9 60
  exit 1
fi

# ── welcome screen ─────────────────────────────────────────────────────────────
whiptail --backtitle "$BT" --title "Welcome" \
  --msgbox "\
Welcome to the 4ham Spectrum Analysis installer!

This wizard will:
  1. Install system packages (SoapySDR, RTL-SDR, Python, Node.js, third-party decoders)
  2. Optionally build the RTL-SDR Blog v4 driver from source
  3. Optionally install OpenAI Whisper for SSB voice transcription
  4. Optionally install Direwolf for APRS packet decoding
  5. Create the Python virtual environment
  6. Install frontend JavaScript dependencies (npm)
  7. Set up your admin account (stored securely in the local DB)
  8. Create the service environment file (.env in project root)
  9. Validate critical runtime dependencies
 10. Install and start the background service (systemd)

Requirements: internet access and sudo rights.
Detected Linux: ${OS_PRETTY_NAME} (supported).

Press Enter to continue." \
  19 68

# ── RTL-SDR dongle version ─────────────────────────────────────────────────────
_rtlv4=0
_rtlv4_label="Standard (v1/v2/v3 or other SoapySDR dongle)"
if whiptail --backtitle "$BT" --title "RTL-SDR Dongle" \
  --yesno "\
Do you have an RTL-SDR Blog v4 dongle?

  YES  ->  Build the v4 driver from source (~5 minutes).
  NO   ->  Use the standard driver from apt.

The RTL-SDR Blog v4 requires a different driver and
will NOT work with the standard apt package." \
  13 66; then
  _rtlv4=1
  _rtlv4_label="RTL-SDR Blog v4 (build from source)"
fi

# ── ASR / Whisper ──────────────────────────────────────────────────────────────
_install_whisper=0
_whisper_model_size="tiny"
_whisper_label="Não (adicionar depois: pip install openai-whisper)"
_whisper_choice=$(whiptail --backtitle "$BT" \
  --title "ASR Voice Transcription (OpenAI Whisper)" \
  --menu "\
Whisper converte áudio SSB/USB em texto legível, visível
no log de eventos em tempo real. Escolha o modelo:

Qualidade em SSB com QRM/QRN (todos correm em CPU):
  tiny  -> fraca  | rápido  | ~75 MB + ~200 MB PyTorch
  base  -> boa    | médio   | ~150 MB + ~200 MB PyTorch  [recomendado]
  small -> muito  | lento   | ~500 MB + ~200 MB PyTorch
  no    -> não instalar agora (pip install openai-whisper)" \
  18 72 4 \
  "no"    "Não instalar — adicionar depois manualmente" \
  "tiny"  "tiny   ~75 MB  — rápido, qualidade fraca em SSB com ruído" \
  "base"  "base  ~150 MB  — RECOMENDADO, bom equilíbrio para SSB" \
  "small" "small ~500 MB  — maior precisão, lento em CPU" \
  3>&1 1>&2 2>&3) || exit 0
case "$_whisper_choice" in
  tiny)
    _install_whisper=1
    _whisper_model_size="tiny"
    _whisper_label="Sim — tiny  (~75 MB, rápido, qualidade fraca em SSB)"
    ;;
  base)
    _install_whisper=1
    _whisper_model_size="base"
    _whisper_label="Sim — base (~150 MB, recomendado para SSB)"
    ;;
  small)
    _install_whisper=1
    _whisper_model_size="small"
    _whisper_label="Sim — small (~500 MB, melhor precisão, lento em CPU)"
    ;;
  *)
    _install_whisper=0
    _whisper_model_size="tiny"
    _whisper_label="Não (adicionar depois: pip install openai-whisper)"
    ;;
esac

# ── Direwolf / APRS ────────────────────────────────────────────────────────────
_install_direwolf=0
_direwolf_label="Não (adicionar depois: sudo apt install direwolf)"
_direwolf_callsign="N0CALL"
if whiptail --backtitle "$BT" --title "APRS — Direwolf TNC" \
  --yesno "\
Instalar Direwolf para descodificação APRS?

Direwolf é um TNC (Terminal Node Controller) por software
que descodifica pacotes AX.25/APRS na frequência 144.800 MHz
(Região 1 IARU).

O backend liga-se ao Direwolf via KISS TCP (porta 8001)
para receber pacotes APRS em tempo real.

  SIM  ->  Instalar Direwolf e criar configuração KISS.
  NÃO  ->  Não instalar (pode adicionar manualmente depois)." \
  18 70; then
  _install_direwolf=1
  _direwolf_label="Sim (Direwolf + KISS TCP na porta 8001)"
fi

# ── installation mode ──────────────────────────────────────────────────────────
_install_mode="systemd"
_install_mode_label="systemd (auto-start on boot)"
_mode_choice=$(whiptail --backtitle "$BT" --title "Installation Mode" \
  --menu "How do you want to run 4ham-spectrum-analysis?" \
  14 78 2 \
  "systemd" "Install as a systemd service (recommended for production)" \
  "manual" "Manual start/stop by the user (no systemd service install)" \
  3>&1 1>&2 2>&3) || exit 0
if [[ "${_mode_choice}" == "manual" ]]; then
  _install_mode="manual"
  _install_mode_label="manual start/stop (no systemd)"
fi

# ── admin username ─────────────────────────────────────────────────────────────
_admin_user=""
while [[ -z "$_admin_user" ]]; do
  _admin_user=$(whiptail --backtitle "$BT" --title "Admin Account - Username" \
    --inputbox "Choose a username for the web interface admin account:" \
    9 66 "admin" 3>&1 1>&2 2>&3) || exit 0
  _admin_user="${_admin_user//[[:space:]]/}"
  if [[ -z "$_admin_user" ]]; then
    whiptail --backtitle "$BT" --title "Error" \
      --msgbox "Username cannot be empty." 7 42
  fi
done

# ── admin password ─────────────────────────────────────────────────────────────
_admin_pass=""
while true; do
  _admin_pass=$(whiptail --backtitle "$BT" --title "Admin Account - Password" \
    --passwordbox "Enter a password for '${_admin_user}':" \
    9 66 "" 3>&1 1>&2 2>&3) || exit 0

  if [[ -z "$_admin_pass" ]]; then
    whiptail --backtitle "$BT" --title "Error" \
      --msgbox "Password cannot be empty." 7 42
    continue
  fi

  if [[ ${#_admin_pass} -lt 8 ]]; then
    if ! whiptail --backtitle "$BT" --title "Weak Password" \
      --yesno "Password is shorter than 8 characters.\nContinue anyway?" 8 54; then
      continue
    fi
  fi

  _admin_pass2=$(whiptail --backtitle "$BT" --title "Admin Account - Confirm Password" \
    --passwordbox "Confirm password:" \
    9 66 "" 3>&1 1>&2 2>&3) || exit 0

  if [[ "$_admin_pass" == "$_admin_pass2" ]]; then
    break
  fi
  whiptail --backtitle "$BT" --title "Error" \
    --msgbox "Passwords do not match. Please try again." 7 52
done
unset _admin_pass2

# ── confirmation ───────────────────────────────────────────────────────────────
whiptail --backtitle "$BT" --title "Confirm Installation" \
  --yesno "\
Ready to install. Summary:

  SDR driver  :  $_rtlv4_label
  ASR Whisper :  $_whisper_label
  APRS/Direwolf: $_direwolf_label
  Install mode:  $_install_mode_label
  Admin user  :  $_admin_user
  Install log :  $LOG_FILE

Proceed with installation?" \
  17 70 || exit 0

# ── installation with progress gauge ──────────────────────────────────────────
start_gauge "Installing 4ham-spectrum-analysis - please wait..."

gauge_step 3 "Updating package lists..."
run_sudo apt-get update -qq >> "$LOG_FILE" 2>&1 \
  || abort "apt-get update failed"

gauge_step 18 "Installing system packages (SoapySDR, Python, Node.js, decoders, build tools)..."
run_sudo apt-get install -y \
  python3-venv python3-pip git \
  nodejs npm \
  soapysdr-tools libsoapysdr-dev \
  soapysdr-module-rtlsdr rtl-sdr \
  wsjtx usbutils \
  build-essential cmake libusb-1.0-0-dev \
  ffmpeg \
  >> "$LOG_FILE" 2>&1 \
  || abort "System package installation failed"
# python3-soapysdr may not exist on all distros — install separately (non-fatal)
run_sudo apt-get install -y python3-soapysdr >> "$LOG_FILE" 2>&1 || true

if [[ $_rtlv4 -eq 1 ]]; then
  gauge_step 33 "Removing conflicting standard rtl-sdr package..."
  run_sudo apt-get remove -y rtl-sdr librtlsdr0 librtlsdr-dev >> "$LOG_FILE" 2>&1 || true

  gauge_step 37 "Cloning RTL-SDR Blog v4 driver source..."
  _rtltmp="$(mktemp -d /tmp/rtlsdr-XXXXXX)"
  git clone --depth=1 https://github.com/rtlsdrblog/rtl-sdr-blog "$_rtltmp/src" \
    >> "$LOG_FILE" 2>&1 || abort "Failed to clone rtl-sdr-blog repository"

  gauge_step 43 "Configuring RTL-SDR Blog v4 driver (cmake)..."
  cmake -B "$_rtltmp/build" "$_rtltmp/src" \
    -DINSTALL_UDEV_RULES=ON -DCMAKE_BUILD_TYPE=Release -Wno-dev \
    >> "$LOG_FILE" 2>&1 || abort "cmake configuration failed"

  gauge_step 50 "Compiling RTL-SDR Blog v4 driver (make - takes a few minutes)..."
  make -C "$_rtltmp/build" -j"$(nproc)" >> "$LOG_FILE" 2>&1 || abort "Compilation failed"

  gauge_step 58 "Installing RTL-SDR Blog v4 driver..."
  run_sudo make -C "$_rtltmp/build" install >> "$LOG_FILE" 2>&1 || abort "Driver install failed"
  run_sudo ldconfig >> "$LOG_FILE" 2>&1

  gauge_step 62 "Blacklisting conflicting kernel modules..."
  run_sudo tee /etc/modprobe.d/blacklist-rtl.conf >/dev/null <<'BLACKLIST'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2832_sdr
blacklist rtl2830
BLACKLIST
  run_sudo modprobe -r dvb_usb_rtl28xxu rtl2832_sdr rtl2832 >> "$LOG_FILE" 2>&1 || true

  rm -rf "$_rtltmp"

  gauge_step 63 "Re-installing SoapySDR RTL module (uses v4 driver library)..."
  run_sudo apt-get install -y soapysdr-module-rtlsdr >> "$LOG_FILE" 2>&1 || true
fi

gauge_step 65 "Configuring USB and audio device access (plugdev + audio groups)..."
if ! id -nG "$(id -un)" 2>/dev/null | grep -qw plugdev; then
  run_sudo usermod -aG plugdev "$(id -un)" >> "$LOG_FILE" 2>&1
fi
if ! id -nG "$(id -un)" 2>/dev/null | grep -qw audio; then
  run_sudo usermod -aG audio "$(id -un)" >> "$LOG_FILE" 2>&1
fi

gauge_step 67 "Installing SDR udev rules..."
# RTL-SDR udev rules (covers RTL2832U and RTL2838 chipsets)
if [[ ! -f /etc/udev/rules.d/20-rtlsdr.rules ]]; then
  run_sudo tee /etc/udev/rules.d/20-rtlsdr.rules >/dev/null <<'UDEVRULES'
# RTL-SDR USB device permissions — created by 4ham-spectrum-analysis installer
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2832", GROUP="plugdev", MODE="0660", SYMLINK+="rtl_sdr"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", GROUP="plugdev", MODE="0660", SYMLINK+="rtl_sdr"
UDEVRULES
  run_sudo udevadm control --reload-rules >> "$LOG_FILE" 2>&1 || true
  run_sudo udevadm trigger >> "$LOG_FILE" 2>&1 || true
fi

gauge_step 69 "Blacklisting conflicting DVB kernel modules..."
if [[ ! -f /etc/modprobe.d/blacklist-rtl.conf ]]; then
  run_sudo tee /etc/modprobe.d/blacklist-rtl.conf >/dev/null <<'BLACKLIST'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2832_sdr
blacklist rtl2830
BLACKLIST
fi
run_sudo modprobe -r dvb_usb_rtl28xxu rtl2832_sdr rtl2832 >> "$LOG_FILE" 2>&1 || true

gauge_step 72 "Creating Python virtual environment..."
# Recreate venv if system has SoapySDR but venv cannot import it
if [[ -x "$PYTHON_BIN" ]]; then
  if python3 -c "import SoapySDR" >/dev/null 2>&1 && ! "$PYTHON_BIN" -c "import SoapySDR" >/dev/null 2>&1; then
    rm -rf "$VENV_DIR"
  fi
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  python3 -m venv --system-site-packages "$VENV_DIR" >> "$LOG_FILE" 2>&1 \
    || abort "Failed to create Python venv"
fi

gauge_step 78 "Creating project environment defaults (.env)..."
# Write .env if missing; inject missing decoder keys into existing .env
_env_defaults=(
  "FT_EXTERNAL_ENABLE=1"
  "FT_EXTERNAL_MODES=FT8,FT4"
  "DIREWOLF_KISS_ENABLE=${_install_direwolf}"
  "DIREWOLF_AUTOSTART=${_install_direwolf}"
  "DIREWOLF_CMD=direwolf -t 0 -p -c ${ROOT_DIR}/config/direwolf.conf"
  "SSB_INTERNAL_ENABLE=1"
  "WHISPER_MODEL_SIZE=${_whisper_model_size:-tiny}"
)
if [[ -f "$ENV_FILE" ]]; then
  for _kv in "${_env_defaults[@]}"; do
    _var="${_kv%%=*}"
    if ! grep -q "^${_var}=" "$ENV_FILE" 2>/dev/null; then
      printf '%s\n' "$_kv" >> "$ENV_FILE"
    fi
  done
else
  cat > "$ENV_FILE" <<EOF
# 4ham Spectrum Analysis service environment
APP_HOST=127.0.0.1
APP_PORT=8000
FT_EXTERNAL_ENABLE=1
FT_EXTERNAL_MODES=FT8,FT4
DIREWOLF_KISS_ENABLE=${_install_direwolf}
DIREWOLF_AUTOSTART=${_install_direwolf}
DIREWOLF_CMD=direwolf -t 0 -p -c ${ROOT_DIR}/config/direwolf.conf
SSB_INTERNAL_ENABLE=1
WHISPER_MODEL_SIZE=${_whisper_model_size:-tiny}
EOF
fi

gauge_step 84 "Installing Python dependencies..."
"$PYTHON_BIN" -m pip install --quiet --upgrade pip >> "$LOG_FILE" 2>&1
"$PYTHON_BIN" -m pip install --quiet -r "$ROOT_DIR/backend/requirements.txt" \
  >> "$LOG_FILE" 2>&1 || abort "pip install failed"

gauge_step 88 "Installing frontend JavaScript dependencies (npm)..."
npm --prefix "$ROOT_DIR/frontend" install --no-fund --no-audit \
  >> "$LOG_FILE" 2>&1 || abort "npm install failed for frontend"

if [[ $_install_whisper -eq 1 ]]; then
  # On x86_64 install CPU-only PyTorch first to avoid pulling CUDA wheels
  # (~200 MB CPU build vs ~915 MB CUDA build). On ARM (Raspberry Pi) the
  # ARM torch wheel is already CPU-only so no special handling needed.
  if [[ "$(uname -m)" == "x86_64" ]]; then
    gauge_step 90 "Installing PyTorch CPU-only (~200 MB download, please wait)..."
    "$PYTHON_BIN" -m pip install --quiet torch \
      --index-url https://download.pytorch.org/whl/cpu \
      >> "$LOG_FILE" 2>&1 || { \
        echo "[WARN] torch CPU install failed — Whisper ASR will not be available" >> "$LOG_FILE"; \
        _install_whisper=0; }
  fi
  if [[ $_install_whisper -eq 1 ]]; then
    gauge_step 92 "Installing OpenAI Whisper package (~50 MB, modelo ${_whisper_model_size} descarrega na 1.ª execução)..."
    "$PYTHON_BIN" -m pip install --quiet openai-whisper \
      >> "$LOG_FILE" 2>&1 || { \
        echo "[WARN] openai-whisper install failed — ASR will not be available" >> "$LOG_FILE"; }
  fi
fi

if [[ $_install_direwolf -eq 1 ]]; then
  gauge_step 93 "Installing Direwolf TNC for APRS..."
  run_sudo apt-get install -y direwolf >> "$LOG_FILE" 2>&1 || { \
    echo "[WARN] Direwolf install failed — APRS will not be available" >> "$LOG_FILE"; \
    _install_direwolf=0; }

  if [[ $_install_direwolf -eq 1 ]]; then
    # ── Detect ALSA capture devices for Direwolf ─────────────────────────
    close_gauge
    _dw_adevice="null null"
    _dw_adevice_label="null (sem áudio — configurar depois)"
    _alsa_menu_items=()
    _alsa_menu_items+=("null" "Sem áudio — configurar depois manualmente")
    _alsa_menu_items+=("default" "Dispositivo ALSA/PulseAudio por omissão")

    # Parse arecord -l to build hw:CARD,DEV entries
    while IFS= read -r _aline; do
      if [[ "$_aline" =~ ^card\ ([0-9]+):\ ([^\[]+)\[([^\]]+)\].*device\ ([0-9]+):\ (.+)\[(.*)\] ]]; then
        _acard="${BASH_REMATCH[1]}"
        _adev="${BASH_REMATCH[4]}"
        _aname="${BASH_REMATCH[3]}"
        _adesc="${BASH_REMATCH[6]}"
        _alsa_hw="plughw:${_acard},${_adev}"
        _alsa_menu_items+=("${_alsa_hw}" "${_aname} — ${_adesc}")
      fi
    done < <(arecord -l 2>/dev/null || true)

    _item_count=$(( ${#_alsa_menu_items[@]} / 2 ))
    _menu_height=$(( _item_count + 8 ))
    [[ $_menu_height -gt 22 ]] && _menu_height=22

    _dw_choice=$(whiptail --backtitle "$BT" \
      --title "APRS — Dispositivo de Áudio para Direwolf" \
      --menu "\
Selecione o dispositivo de captura de áudio (entrada) para
o Direwolf usar na descodificação APRS.

Ligue o rádio (144.800 MHz) à entrada de áudio (line-in)
da placa de som antes de iniciar o Direwolf.

Se não souber qual escolher, selecione 'null' e
configure depois em config/direwolf.conf." \
      "$_menu_height" 78 "$_item_count" \
      "${_alsa_menu_items[@]}" \
      3>&1 1>&2 2>&3) || _dw_choice="null"

    case "$_dw_choice" in
      null)
        _dw_adevice="null null"
        _dw_adevice_label="null (sem áudio — configurar depois)"
        ;;
      default)
        _dw_adevice="default"
        _dw_adevice_label="default (ALSA/PulseAudio)"
        ;;
      *)
        _dw_adevice="${_dw_choice} null"
        _dw_adevice_label="${_dw_choice} (só receção)"
        ;;
    esac

    start_gauge "Installing 4ham-spectrum-analysis - please wait..."
    gauge_step 94 "Creating Direwolf configuration for KISS TCP..."
    mkdir -p "$ROOT_DIR/config"
    if [[ ! -f "$ROOT_DIR/config/direwolf.conf" ]]; then
      cat > "$ROOT_DIR/config/direwolf.conf" <<DWEOF
# ──────────────────────────────────────────────────────────────
# Direwolf configuration for 4ham-spectrum-analysis (APRS)
# Generated by install.sh — $(date +%Y-%m-%d)
# ──────────────────────────────────────────────────────────────

# Station callsign
MYCALL ${_direwolf_callsign}

# ── Audio device ──────────────────────────────────────────────
# Detected and selected during installation.
# To change later, edit this file or re-run the installer.
#
# Options:
#   plughw:CARD,DEV  — ALSA hardware device (soundcard line-in)
#   default          — system default audio device
#   null null        — no audio (test mode only)
#
# For rtl_fm pipe mode (receive via RTL-SDR on 144.800 MHz):
#   rtl_fm -f 144.800e6 -s 22050 -g 40 - | direwolf -c config/direwolf.conf -r 22050 -
ADEVICE ${_dw_adevice}

# Channel 0 — 1200 baud AFSK modem (APRS standard)
CHANNEL 0
MODEM 1200

# ── KISS TCP server ──────────────────────────────────────────
# The 4ham backend connects here to receive decoded APRS frames.
KISSPORT 8001

# ── APRS settings ────────────────────────────────────────────
# Receive only — no digipeating or beaconing by default.
# Uncomment and configure if you want to beacon your position:
# PBEACON delay=1 every=30 overlay=S symbol="igate" \\
#   lat=00^00.00N long=000^00.00W \\
#   comment="4ham iGate"

# Disable AGWPE port (only KISS TCP is used)
AGWPORT 0
DWEOF
    fi
  fi
fi

gauge_step 95 "Saving admin credentials to database..."
mkdir -p "$ROOT_DIR/data"

# Write the Python setup script to a temp file so we can pipe the password
# via stdin without conflict — the password never appears in argv or env vars.
_tmp_py="$(mktemp /tmp/4ham-setup-XXXXXX.py)"
_TMPFILES+=("$_tmp_py")
chmod 600 "$_tmp_py"

cat > "$_tmp_py" << 'PYEOF'
import sys, os, sqlite3
sys.path.insert(0, os.path.join(sys.argv[1], "backend"))
import bcrypt

root     = sys.argv[1]
username = sys.argv[2]
password = sys.stdin.read()   # piped via stdin — never in argv or env

pw_hash = bcrypt.hashpw(
    password.encode("utf-8"),
    bcrypt.gensalt(rounds=12),
).decode("utf-8")

db_path = os.path.join(root, "data", "events.sqlite")
conn = sqlite3.connect(db_path)
conn.execute(
    "CREATE TABLE IF NOT EXISTS settings "
    "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
)
for key, val in [
    ("_auth_user",      username),
    ("_auth_pass_hash", pw_hash),
    ("_auth_enabled",   "1"),
]:
    conn.execute(
        "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
        (key, val),
    )
conn.commit()
conn.close()
PYEOF

printf '%s' "$_admin_pass" \
  | "$PYTHON_BIN" "$_tmp_py" "$ROOT_DIR" "$_admin_user" >> "$LOG_FILE" 2>&1 \
  || abort "Failed to save admin credentials"

rm -f "$_tmp_py"
unset _admin_pass

gauge_step 96 "Validating required runtime dependencies..."
_missing_deps=""
if ! _missing_deps="$(validate_runtime_dependencies)"; then
  abort "Missing required runtime dependencies after install: ${_missing_deps}"
fi

if [[ "$_install_mode" == "systemd" ]]; then
  gauge_step 98 "Installing and enabling systemd service..."
  bash "$ROOT_DIR/scripts/install_systemd_service.sh" install >> "$LOG_FILE" 2>&1 \
    || abort "Service installation failed"
else
  gauge_step 98 "Skipping systemd service install (manual mode selected)..."
fi

close_gauge

# ── desktop shortcut (optional — only when a graphical session is detected) ────
_desktop_created=0
if [[ -n "${XDG_CURRENT_DESKTOP:-}" || -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ]]; then
  _desktop_dir="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
  _app_dir="$HOME/.local/share/applications"
  _desktop_file="4ham-spectrum-analysis.desktop"
  _launcher="$ROOT_DIR/scripts/4ham_launcher.sh"

  if whiptail --backtitle "$BT" --title "Desktop Shortcut" \
    --yesno "Create a desktop shortcut?

Opens an interactive menu with:
  • Open Dashboard in Browser
  • Start / Restart / Stop Server" 12 60; then

    cat > "/tmp/$_desktop_file" <<DEOF
[Desktop Entry]
Version=1.0
Name=4ham Spectrum Analysis
Comment=SDR Spectrum Analyser — CT7BFV
GenericName=Spectrum Analyser
Exec="$_launcher"
Icon=utilities-system-monitor
Terminal=true
Type=Application
Categories=HamRadio;Science;Education;
StartupNotify=false
DEOF

    mkdir -p "$_desktop_dir" "$_app_dir"
    cp "/tmp/$_desktop_file" "$_desktop_dir/$_desktop_file"
    cp "/tmp/$_desktop_file" "$_app_dir/$_desktop_file"
    chmod +x "$_desktop_dir/$_desktop_file"
    chmod +x "$_app_dir/$_desktop_file"
    rm -f "/tmp/$_desktop_file"

    # Trust the desktop file (GNOME ≥ 3.28)
    if command -v gio >/dev/null 2>&1; then
      gio set "$_desktop_dir/$_desktop_file" metadata::trusted true 2>/dev/null || true
    fi

    _desktop_created=1
  fi
fi

# ── installation complete ──────────────────────────────────────────────────────
_local_ip="$(hostname -I 2>/dev/null | awk '{print $1}' || echo '127.0.0.1')"

_extra_notes=""
if ! id -nG "$(id -un)" 2>/dev/null | grep -qw plugdev; then
  _extra_notes="${_extra_notes}\n\nUSB access: log out and back in (or reboot)\nto activate USB device access for your user."
fi
if [[ $_rtlv4 -eq 1 ]]; then
  _extra_notes="${_extra_notes}\n\nRTL-SDR v4: a reboot is recommended to fully\nactivate the kernel module blacklist."
fi
if [[ $_desktop_created -eq 1 ]]; then
  _extra_notes="${_extra_notes}\n\nDesktop shortcut created. Double-click it\nfor an interactive server control menu."
fi

if [[ "$_install_mode" == "systemd" ]]; then
  whiptail --backtitle "$BT" --title "Installation Complete!" \
    --msgbox "\
4ham-spectrum-analysis is installed and running!

Open in your browser:
  http://${_local_ip}:8000/
  http://127.0.0.1:8000/
  http://${_local_ip}:8000/4ham_academic_analytics.html

Login with:
  Username : $_admin_user
  Password : (the one you set)

Service management:
  Status   ./scripts/install_systemd_service.sh status
  Logs     ./scripts/install_systemd_service.sh logs
  Restart  ./scripts/install_systemd_service.sh restart
  Remove   ./scripts/install_systemd_service.sh uninstall
${_extra_notes}" \
    24 70
else
  whiptail --backtitle "$BT" --title "Installation Complete!" \
    --msgbox "\
4ham-spectrum-analysis is installed (manual mode).

Server control:
  Start    ./scripts/server_control.sh start
  Stop     ./scripts/server_control.sh stop
  Restart  ./scripts/server_control.sh restart
  Status   ./scripts/server_control.sh status
  Logs     ./scripts/server_control.sh logs

Open in your browser:
  http://${_local_ip}:8000/
  http://127.0.0.1:8000/
  http://${_local_ip}:8000/4ham_academic_analytics.html

Login with:
  Username : $_admin_user
  Password : (the one you set)
${_extra_notes}" \
    24 70
fi
