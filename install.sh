#!/usr/bin/env bash
# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
#
# 4ham-spectrum-analysis — Automatic Installer
#
# Usage:
#   chmod +x install.sh
#   ./install.sh
#
# What this does:
#   1. Installs system packages (SoapySDR, RTL-SDR, Python, build tools)
#   2. Optionally builds the RTL-SDR Blog v4 driver from source
#   3. Adds the current user to the 'plugdev' group (USB access)
#   4. Creates a Python virtual environment and installs dependencies
#   5. Sets up the admin account (stored securely in the local database)
#   6. Installs and enables the systemd background service
#   7. Prints the URL to open in the browser

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR"
SERVICE_NAME="4ham-spectrum-analysis"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
DB_DIR="$ROOT_DIR/data"

# ── colour helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "  ${CYAN}▸${NC} $*"; }
ok()      { echo -e "  ${GREEN}✔${NC} $*"; }
warn()    { echo -e "  ${YELLOW}⚠${NC}  $*"; }
error()   { echo -e "  ${RED}✘${NC} $*" >&2; }
section() { echo -e "\n${BOLD}━━━ $* ━━━${NC}"; }

run_sudo() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

# ── banner ──────────────────────────────────────────────────────────────────────
clear
echo -e "${BOLD}${CYAN}"
cat <<'BANNER'
   _  _  _                     ___                  _
  | || || |                   / __)                | |
  | || || | ____ ____   ____ ( (__  ____  ____  ___| |_  ____ _   _ ____
  | ||_|| |/ _  ) _  | / ___)  \__ \|  _ \/ _  )/ ___) |_/ ___) | | |    \
  | |___| ( (/ ( ( | |( (___ _ / __/ | | ( (/ /( (___| |_| |   | |_| | | | |
   \_____/ \____)_||_| \____(_)_____)_| |_|\____)\___)\___)_|    \____|_|_|_|

              S p e c t r u m   A n a l y s i s   —   C T 7 B F V
BANNER
echo -e "${NC}"
echo -e "${BOLD}Automatic Installer${NC}  ·  GNU AGPL-3.0"
echo

# ── step 0: basic checks ────────────────────────────────────────────────────────
section "Checking prerequisites"

if [[ "${EUID}" -eq 0 ]]; then
  error "Do not run this installer as root."
  error "Run as a normal user that has sudo access: ./install.sh"
  exit 1
fi

if ! command -v sudo &>/dev/null; then
  error "'sudo' is not available. Install it first, then re-run."
  exit 1
fi

if ! command -v apt-get &>/dev/null; then
  error "This installer requires apt (Ubuntu, Debian, Raspberry Pi OS, Linux Mint)."
  exit 1
fi

if ! command -v python3 &>/dev/null; then
  error "python3 not found. Install it with: sudo apt install python3"
  exit 1
fi

PYVER_OK=$(python3 -c "import sys; print('ok' if sys.version_info >= (3,10) else 'fail')" 2>/dev/null || echo fail)
if [[ "$PYVER_OK" != "ok" ]]; then
  error "Python 3.10 or later is required. Found: $(python3 --version 2>&1)"
  exit 1
fi

ok "Running as user: $(id -un)"
ok "Python: $(python3 --version)"
ok "OS: $(. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-Linux}" || echo Linux)"

# ── step 1: system packages ─────────────────────────────────────────────────────
section "Installing system packages"

info "Running apt update..."
run_sudo apt-get update -qq

info "Installing SoapySDR, RTL-SDR, Python tools and build tools..."
run_sudo apt-get install -y \
  python3-venv python3-pip git \
  soapysdr-tools libsoapysdr-dev python3-soapysdr \
  soapysdr-module-rtlsdr rtl-sdr \
  build-essential cmake libusb-1.0-0-dev

ok "System packages installed"

# ── step 2: RTL-SDR Blog v4 driver (optional) ──────────────────────────────────
section "RTL-SDR driver"

echo    "The standard 'rtl-sdr' apt package does NOT support the RTL-SDR Blog v4."
echo    "If you have a v4 dongle the driver must be built from source."
echo
read -rp "  Do you have an RTL-SDR Blog v4 dongle? [y/N]: " _rtlv4
_rtlv4="${_rtlv4,,}"

if [[ "$_rtlv4" == "y" || "$_rtlv4" == "yes" ]]; then
  info "Removing standard rtl-sdr package to avoid conflicts..."
  run_sudo apt-get remove -y rtl-sdr librtlsdr0 librtlsdr-dev 2>/dev/null || true

  _RTLTMP="$(mktemp -d)"
  # Clean up temp directory on exit (success or error)
  trap 'rm -rf "$_RTLTMP"' EXIT

  info "Cloning rtl-sdr-blog driver source..."
  git clone --depth=1 https://github.com/rtlsdrblog/rtl-sdr-blog "$_RTLTMP/rtl-sdr-blog"

  info "Building driver (this may take a few minutes)..."
  cmake -B "$_RTLTMP/rtl-sdr-blog/build" "$_RTLTMP/rtl-sdr-blog" \
    -DINSTALL_UDEV_RULES=ON -DCMAKE_BUILD_TYPE=Release -Wno-dev
  make -C "$_RTLTMP/rtl-sdr-blog/build" -j"$(nproc)"
  run_sudo make -C "$_RTLTMP/rtl-sdr-blog/build" install
  run_sudo ldconfig

  info "Blacklisting conflicting kernel modules..."
  run_sudo tee /etc/modprobe.d/blacklist-rtl.conf >/dev/null <<'BLACKLIST'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
BLACKLIST
  run_sudo modprobe -r dvb_usb_rtl28xxu 2>/dev/null || true

  ok "RTL-SDR Blog v4 driver installed"
  warn "A reboot is recommended to activate the kernel module blacklist."
else
  ok "Using standard RTL-SDR driver (already installed via apt)"
fi

# ── step 3: USB access ──────────────────────────────────────────────────────────
section "USB device access"

_CURRENT_USER="$(id -un)"
if id -nG "$_CURRENT_USER" 2>/dev/null | grep -qw plugdev; then
  ok "User '$_CURRENT_USER' is already in the 'plugdev' group"
else
  run_sudo usermod -aG plugdev "$_CURRENT_USER"
  ok "Added '$_CURRENT_USER' to the 'plugdev' group"
  warn "USB access takes effect after you log out and back in (or reboot)."
  warn "The service will start correctly regardless — this affects direct CLI use."
fi

# ── step 4: Python virtual environment ─────────────────────────────────────────
section "Python virtual environment"

if [[ -x "$PYTHON_BIN" ]]; then
  info "Virtual environment already exists — reusing it"
else
  info "Creating virtual environment at .venv/ ..."
  python3 -m venv "$VENV_DIR"
fi

info "Installing Python dependencies (this may take a minute)..."
"$PYTHON_BIN" -m pip install --quiet --upgrade pip
"$PYTHON_BIN" -m pip install --quiet -r "$ROOT_DIR/backend/requirements.txt"

ok "Python environment ready ($(\"$PYTHON_BIN\" --version))"

# ── step 5: admin account setup ────────────────────────────────────────────────
section "Administrator account"

echo    "Create the admin account for the web interface."
echo    "These credentials are stored securely (bcrypt) in the local database."
echo

read -rp "  Admin username [admin]: " _admin_user
_admin_user="${_admin_user:-admin}"

while true; do
  read -rsp "  Admin password: " _admin_pass
  echo
  read -rsp "  Confirm password: " _admin_pass2
  echo
  if [[ "$_admin_pass" == "$_admin_pass2" ]]; then
    break
  fi
  warn "Passwords do not match. Try again."
done

if [[ ${#_admin_pass} -lt 8 ]]; then
  warn "Password is shorter than 8 characters — consider using a stronger one."
fi

info "Saving credentials to database..."
mkdir -p "$DB_DIR"

# Pass password via stdin (never as a command-line argument) to avoid
# exposure in process lists.
printf '%s' "$_admin_pass" | "$PYTHON_BIN" - "$ROOT_DIR" "$_admin_user" <<'PYEOF'
import sys, os, sqlite3

sys.path.insert(0, os.path.join(sys.argv[1], "backend"))
import bcrypt

root     = sys.argv[1]
username = sys.argv[2]
password = sys.stdin.read()          # received via stdin pipe — never in argv

pw_hash = bcrypt.hashpw(
    password.encode("utf-8"),
    bcrypt.gensalt(rounds=12),
).decode("utf-8")

db_path = os.path.join(root, "data", "events.sqlite")
conn = sqlite3.connect(db_path)
conn.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
""")
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
print(f"    Credentials saved for user: {username}")
PYEOF

ok "Admin account '$_admin_user' configured"

# unset password variables as soon as they are no longer needed
unset _admin_pass _admin_pass2

# ── step 6: systemd service ─────────────────────────────────────────────────────
section "Installing systemd service"

info "Installing and enabling the '$SERVICE_NAME' service..."
bash "$ROOT_DIR/scripts/install_systemd_service.sh" install

ok "Service '$SERVICE_NAME' installed and started"

# ── step 7: final summary ───────────────────────────────────────────────────────
_LOCAL_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || echo '127.0.0.1')"

echo
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║           Installation complete!                    ║${NC}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo
echo -e "  ${BOLD}Open in your browser:${NC}"
echo -e "    ${CYAN}http://${_LOCAL_IP}:8000/${NC}        (local network)"
echo -e "    ${CYAN}http://127.0.0.1:8000/${NC}     (this machine)"
echo
echo -e "  ${BOLD}Login with:${NC}"
echo -e "    Username: ${BOLD}$_admin_user${NC}"
echo -e "    Password: (the one you just set)"
echo
echo -e "  ${BOLD}Service management:${NC}"
echo -e "    Status : ${CYAN}./scripts/install_systemd_service.sh status${NC}"
echo -e "    Logs   : ${CYAN}./scripts/install_systemd_service.sh logs${NC}"
echo -e "    Restart: ${CYAN}./scripts/install_systemd_service.sh restart${NC}"
echo -e "    Remove : ${CYAN}./scripts/install_systemd_service.sh uninstall${NC}"
echo
if id -nG "$(id -un)" 2>/dev/null | grep -qw plugdev; then
  true
else
  warn "Remember to log out and back in (or reboot) to activate USB device access."
  echo
fi
