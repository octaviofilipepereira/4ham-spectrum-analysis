#!/usr/bin/env bash
# © 2026 Octavio Filipe Goncalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0
# Complete uninstaller for 4ham-spectrum-analysis (Linux)

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="4ham-spectrum-analysis"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
ENV_FILE="/etc/default/${SERVICE_NAME}"

PURGE_DATA=0
PURGE_SYSTEM_PACKAGES=0
PURGE_ALL=0
ASSUME_YES=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Options:
  --purge-data             Remove local runtime data (data/, logs/, exports/)
  --purge-system-packages  Remove system packages installed for this app
  --purge-all              Full wipe: data + system packages + project folder
  --yes                    Non-interactive mode (assume yes)
  -h, --help               Show this help

Default behavior (safe):
  - Remove systemd service
  - Remove service env file (/etc/default/4ham-spectrum-analysis)
  - Remove local virtualenv (.venv)
  - Remove frontend node_modules/

Examples:
  ./uninstall.sh
  ./uninstall.sh --purge-data
  ./uninstall.sh --purge-data --purge-system-packages --yes
  ./uninstall.sh --purge-all --yes
EOF
}

run_cmd() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

confirm() {
  local prompt="$1"
  if [[ "$ASSUME_YES" -eq 1 ]]; then
    return 0
  fi
  read -r -p "$prompt [y/N]: " ans
  [[ "${ans:-}" =~ ^[Yy]$ ]]
}

for arg in "$@"; do
  case "$arg" in
    --purge-data)
      PURGE_DATA=1
      ;;
    --purge-system-packages)
      PURGE_SYSTEM_PACKAGES=1
      ;;
    --purge-all)
      PURGE_ALL=1
      PURGE_DATA=1
      PURGE_SYSTEM_PACKAGES=1
      ;;
    --yes)
      ASSUME_YES=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      usage
      exit 1
      ;;
  esac
done

echo "Uninstalling ${SERVICE_NAME} from: ${ROOT_DIR}"

if ! confirm "Proceed with uninstall"; then
  echo "Cancelled."
  exit 0
fi

# 1) Service uninstall
if [[ -x "${ROOT_DIR}/scripts/install_systemd_service.sh" ]]; then
  echo "[1/5] Removing systemd service..."
  bash "${ROOT_DIR}/scripts/install_systemd_service.sh" uninstall || true
else
  echo "[1/5] Removing systemd service (fallback)..."
  run_cmd systemctl disable --now "${SERVICE_NAME}" >/dev/null 2>&1 || true
  run_cmd rm -f "${SERVICE_FILE}" || true
  run_cmd systemctl daemon-reload || true
fi

# 2) Remove env file
if run_cmd test -f "${ENV_FILE}"; then
  echo "[2/5] Removing service environment file..."
  run_cmd rm -f "${ENV_FILE}"
else
  echo "[2/5] Service environment file not present."
fi

# 3) Remove local dependencies created by installer
echo "[3/5] Removing local environments/dependencies..."
rm -rf "${ROOT_DIR}/.venv"
rm -rf "${ROOT_DIR}/frontend/node_modules"

# 4) Optional data purge
if [[ "$PURGE_DATA" -eq 1 ]]; then
  if confirm "Purge local data (data/, logs/, exports/)? This is destructive"; then
    echo "[4/5] Purging local data..."
    rm -rf "${ROOT_DIR}/data"
    rm -rf "${ROOT_DIR}/logs"
    rm -rf "${ROOT_DIR}/exports"
  else
    echo "[4/5] Data purge skipped."
  fi
else
  echo "[4/5] Data purge not requested."
fi

# 5) Optional system package purge
if [[ "$PURGE_SYSTEM_PACKAGES" -eq 1 ]]; then
  if confirm "Purge system packages (SoapySDR/RTL/direwolf/wsjtx/nodejs/ffmpeg)?"; then
    echo "[5/5] Purging system packages..."
    run_cmd apt-get remove -y --purge \
      soapysdr-tools libsoapysdr-dev python3-soapysdr \
      soapysdr-module-rtlsdr rtl-sdr direwolf wsjtx \
      ffmpeg nodejs npm usbutils libusb-1.0-0-dev cmake || true
    run_cmd apt-get autoremove -y || true

    if run_cmd test -f /etc/modprobe.d/blacklist-rtl.conf; then
      echo "Removing RTL blacklist file created for RTL-SDR v4..."
      run_cmd rm -f /etc/modprobe.d/blacklist-rtl.conf || true
      echo "Note: Reboot recommended to fully apply driver/module changes."
    fi
  else
    echo "[5/5] System package purge skipped."
  fi
else
  echo "[5/5] System package purge not requested."
fi

if [[ "$PURGE_ALL" -eq 1 ]]; then
  if [[ -z "${ROOT_DIR}" || "${ROOT_DIR}" == "/" || "${ROOT_DIR}" == "." ]]; then
    echo "Refusing to remove unsafe project directory path: '${ROOT_DIR}'" >&2
    exit 1
  fi

  if [[ ! -d "${ROOT_DIR}" ]]; then
    echo "Project directory not found: ${ROOT_DIR}" >&2
    exit 1
  fi

  if confirm "FINAL WARNING: remove the entire project directory '${ROOT_DIR}'?"; then
    echo "[extra] Removing project directory..."
    rm -rf "${ROOT_DIR}"
    echo "Project directory removed."
    exit 0
  else
    echo "Project directory removal skipped."
  fi
fi

echo "Uninstall completed."
