#!/usr/bin/env bash
# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
#
# 4ham Spectrum Analysis — Desktop Launcher
# Interactive menu for server control.

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTROL="$ROOT_DIR/scripts/server_control.sh"
ENV_FILE="$ROOT_DIR/.env"

read_env_value() {
  local key="$1"
  local default_value="$2"
  local value="${!key:-}"
  if [[ -n "$value" ]]; then
    echo "$value"
    return 0
  fi
  if [[ -f "$ENV_FILE" ]]; then
    value="$(grep -E "^(export[[:space:]]+)?${key}=" "$ENV_FILE" | tail -n 1 || true)"
    if [[ -n "$value" ]]; then
      value="${value#export }"
      value="${value#*=}"
      value="${value%\"}"
      value="${value#\"}"
      value="${value%\'}"
      value="${value#\'}"
    fi
  fi
  echo "${value:-$default_value}"
}

APP_HOST="$(read_env_value APP_HOST "127.0.0.1")"
APP_PORT="$(read_env_value APP_PORT "8000")"
URL_HOST="127.0.0.1"
if [[ "$APP_HOST" != "0.0.0.0" && "$APP_HOST" != "::" ]]; then
  URL_HOST="$APP_HOST"
fi
URL="http://${URL_HOST}:${APP_PORT}/"

# ── colours ────────────────────────────────────────────────────────────────────
RST='\033[0m'
BOLD='\033[1m'
GREEN='\033[32m'
RED='\033[31m'
CYAN='\033[36m'
YELLOW='\033[33m'

is_running() {
  pgrep -af 'uvicorn app.main:app' >/dev/null 2>&1
}

show_status() {
  if is_running; then
    echo -e "  Server: ${GREEN}${BOLD}RUNNING${RST}"
  else
    echo -e "  Server: ${RED}${BOLD}STOPPED${RST}"
  fi
  echo
}

banner() {
  clear
  echo -e "${CYAN}${BOLD}"
  echo "  ╔══════════════════════════════════════════╗"
  echo "  ║     4ham Spectrum Analysis — CT7BFV      ║"
  echo "  ╠══════════════════════════════════════════╣"
  echo -e "  ╚══════════════════════════════════════════╝${RST}"
  echo
  show_status
}

menu() {
  banner
  echo -e "  ${BOLD}1)${RST}  Open Dashboard in Browser"
  echo -e "  ${BOLD}2)${RST}  Start Server"
  echo -e "  ${BOLD}3)${RST}  Restart Server"
  echo -e "  ${BOLD}4)${RST}  Stop Server"
  echo
  echo -e "  ${BOLD}0)${RST}  Exit"
  echo
  echo -n "  Select [0-4]: "
}

pause() {
  echo
  echo -n "  Press Enter to continue..."
  read -r
}

# ── main loop ──────────────────────────────────────────────────────────────────
while true; do
  menu
  read -r choice

  case "$choice" in
    1)
      if is_running; then
        echo
        echo -e "  ${GREEN}Opening browser...${RST}"
        xdg-open "$URL" 2>/dev/null &
        pause
      else
        echo
        echo -e "  ${RED}Server is not running. Start it first (option 2).${RST}"
        pause
      fi
      ;;
    2)
      echo
      echo -e "  ${YELLOW}Starting server...${RST}"
      "$CONTROL" start
      pause
      ;;
    3)
      echo
      echo -e "  ${YELLOW}Restarting server...${RST}"
      "$CONTROL" restart
      pause
      ;;
    4)
      echo
      echo -e "  ${YELLOW}Stopping server...${RST}"
      "$CONTROL" stop
      pause
      ;;
    0|q|Q)
      echo
      echo -e "  ${CYAN}73 de CT7BFV${RST}"
      echo
      exit 0
      ;;
    *)
      ;;
  esac
done
