#!/usr/bin/env bash
# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
#
# 4ham-spectrum-analysis — Enable LoRa APRS (gr-lora_sdr) on an existing install
#
# Use this script when you already have 4ham installed and you want to
# add LoRa APRS decoding (433.775 MHz) via the gr-lora_sdr GNU Radio
# Out-Of-Tree module without re-running the full installer.
#
# What it does:
#   1. Installs GNU Radio + build dependencies via apt-get.
#   2. Clones tapparelj/gr-lora_sdr into /opt/gr-lora_sdr (skips if present).
#   3. Configures and builds it with CMake, then installs to /usr/local.
#   4. Refreshes the dynamic linker cache (ldconfig).
#   5. Verifies the Python module 'gnuradio.lora_sdr' imports successfully.
#   6. Prints next-steps to enable LoRa APRS in the 4ham Admin Config panel.
#
# Usage:
#   sudo bash scripts/enable_lora_aprs.sh
#   # or
#   bash scripts/enable_lora_aprs.sh   (will prompt for sudo when needed)
#
# Note: the build typically takes 5–15 minutes depending on hardware.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC_DIR="${GR_LORA_SDR_SRC:-/opt/gr-lora_sdr}"
REPO_URL="${GR_LORA_SDR_REPO:-https://github.com/tapparelj/gr-lora_sdr.git}"

# Colours
B="\033[1m"; G="\033[32m"; Y="\033[33m"; R="\033[31m"; C="\033[36m"; N="\033[0m"

run_sudo() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

banner() {
  echo
  echo -e "${B}${C}=====================================================${N}"
  echo -e "${B}${C} 4ham-spectrum-analysis — Enable LoRa APRS${N}"
  echo -e "${B}${C} (gr-lora_sdr, 433.775 MHz / 70 cm)${N}"
  echo -e "${B}${C}=====================================================${N}"
  echo
}

check_distro() {
  if [[ ! -f /etc/os-release ]]; then
    echo -e "${R}Error:${N} /etc/os-release not found. This script supports Debian/Ubuntu-based systems." >&2
    exit 1
  fi
  # shellcheck disable=SC1091
  source /etc/os-release
  case "${ID:-}" in
    ubuntu|debian|raspbian|linuxmint|pop|elementary)
      echo -e "Detected distribution: ${G}${PRETTY_NAME:-$ID}${N}"
      ;;
    *)
      echo -e "${Y}Warning:${N} distribution '${ID:-unknown}' is not officially supported."
      echo "         The script will try apt-get anyway."
      ;;
  esac
}

probe_python_module() {
  python3 - <<'PY' 2>/dev/null
import importlib.util, sys
sys.exit(0 if importlib.util.find_spec("gnuradio.lora_sdr") else 1)
PY
}

install_build_deps() {
  echo -e "${B}Installing GNU Radio + build dependencies via apt-get...${N}"
  echo "(you may be prompted for your sudo password)"
  echo
  run_sudo apt-get update
  run_sudo apt-get install -y \
    git cmake build-essential pkg-config \
    gnuradio gnuradio-dev \
    libsndfile1-dev libgmp-dev \
    swig python3-dev python3-numpy
  echo -e "${G}Build dependencies installed.${N}"
}

clone_or_update_repo() {
  if [[ -d "$SRC_DIR/.git" ]]; then
    echo -e "Source tree already present at ${C}${SRC_DIR}${N} — pulling latest."
    run_sudo git -C "$SRC_DIR" pull --ff-only || true
    return 0
  fi
  echo -e "Cloning ${C}${REPO_URL}${N} into ${C}${SRC_DIR}${N}"
  run_sudo mkdir -p "$(dirname "$SRC_DIR")"
  run_sudo git clone --depth 1 "$REPO_URL" "$SRC_DIR"
}

build_and_install() {
  echo -e "${B}Building gr-lora_sdr (this may take several minutes)...${N}"
  local build_dir="$SRC_DIR/build"
  run_sudo mkdir -p "$build_dir"
  run_sudo bash -c "cd '$build_dir' && cmake -DCMAKE_INSTALL_PREFIX=/usr/local .. && make -j\$(nproc) && make install && ldconfig"
  echo -e "${G}Build & install complete.${N}"
}

verify_install() {
  if probe_python_module; then
    echo -e "${G}Verified: 'import gnuradio.lora_sdr' works.${N}"
    return 0
  fi
  echo -e "${R}Error:${N} Python module 'gnuradio.lora_sdr' not importable after install." >&2
  echo "         Check that PYTHONPATH includes the GNU Radio site-packages directory." >&2
  exit 1
}

# Persist FEATURE_LORA_APRS=true in the project's .env so the backend exposes
# LoRa controls (and the lifespan auto-starts the UDP listener when enabled).
# Idempotent: replaces an existing line or appends if missing.
enable_feature_flag() {
  local env_file="$ROOT_DIR/.env"
  if [[ ! -f "$env_file" ]]; then
    echo "FEATURE_LORA_APRS=true" > "$env_file"
    echo -e "${G}Created${N} $env_file with FEATURE_LORA_APRS=true"
    return 0
  fi
  if grep -qE '^[[:space:]]*(export[[:space:]]+)?FEATURE_LORA_APRS=' "$env_file"; then
    # Replace existing value (handles both `KEY=` and `export KEY=` forms).
    sed -i -E 's|^[[:space:]]*(export[[:space:]]+)?FEATURE_LORA_APRS=.*$|FEATURE_LORA_APRS=true|' "$env_file"
    echo -e "${G}Updated${N} FEATURE_LORA_APRS=true in $env_file"
  else
    printf '\nFEATURE_LORA_APRS=true\n' >> "$env_file"
    echo -e "${G}Appended${N} FEATURE_LORA_APRS=true to $env_file"
  fi
  echo -e "${Y}Note:${N} restart the backend (e.g. ${C}bash scripts/server_control.sh restart${N}) for the flag to take effect."
}

print_next_steps() {
  echo
  echo -e "${B}${G}LoRa APRS support is now ready.${N}"
  echo
  echo -e "${B}Next steps:${N}"
  echo
  echo -e "  ${B}1.${N} Open the 4ham web interface."
  echo -e "  ${B}2.${N} Reload the page (Ctrl+R / F5)."
  echo -e "  ${B}3.${N} Open ${C}Admin Config${N} → look for the section"
  echo -e "        ${C}LoRa APRS Packet Decoding (gr-lora_sdr)${N}."
  echo -e "  ${B}4.${N} The badge should now show ${G}\"gr-lora_sdr installed\"${N}."
  echo -e "  ${B}5.${N} Tick ${C}\"Enable LoRa APRS packet decoding\"${N}"
  echo -e "        and click ${C}\"Save LoRa APRS setting\"${N}."
  echo
  echo -e "${B}Notes:${N}"
  echo -e "  • The backend listens for decoded LoRa frames on UDP 5687"
  echo -e "    (override with LORA_APRS_PORT in .env)."
  echo -e "  • You must run a gr-lora_sdr flowgraph that forwards decoded"
  echo -e "    payloads to that UDP port. Example flowgraphs are in"
  echo -e "    ${C}${SRC_DIR}/examples${N}."
  echo -e "  • LoRa APRS uses 433.775 MHz (70 cm)."
  echo -e "  • Antenna: a dual-band VHF/UHF (e.g. Diamond X50) is suitable."
  echo
}

main() {
  banner
  check_distro
  if probe_python_module; then
    echo -e "gr-lora_sdr is ${G}already installed${N} — re-running build to update."
  fi
  install_build_deps
  clone_or_update_repo
  build_and_install
  verify_install
  enable_feature_flag
  print_next_steps
}

main "$@"
