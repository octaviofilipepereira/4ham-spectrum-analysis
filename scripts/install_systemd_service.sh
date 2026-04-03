#!/usr/bin/env bash
# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 16:27:19 UTC

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="4ham-spectrum-analysis"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SERVICE_TEMPLATE="$ROOT_DIR/scripts/${SERVICE_NAME}.service.template"
ENV_FILE="$ROOT_DIR/.env"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"

usage() {
  cat <<EOF
Usage: $(basename "$0") <install|uninstall|status|logs|restart|stop>

Commands:
  install    Install and enable the systemd service
  uninstall  Stop and remove the systemd service
  status     Show service status
  logs       Follow service logs (journalctl)
  restart    Restart service and show status
  stop       Stop service (keep installed)
EOF
}

run_cmd() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

ensure_prereqs() {
  if [[ ! -f "$SERVICE_TEMPLATE" ]]; then
    echo "Missing service template: $SERVICE_TEMPLATE" >&2
    exit 1
  fi

  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Python environment not found at $PYTHON_BIN" >&2
    echo "Create it first: python3 -m venv .venv && ./.venv/bin/python -m pip install -r backend/requirements.txt" >&2
    exit 1
  fi
}

service_user() {
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    echo "$SUDO_USER"
    return
  fi
  id -un
}

write_service() {
  local user
  user="$(service_user)"

  local escaped_root escaped_python escaped_user
  escaped_root="$(printf '%s' "$ROOT_DIR" | sed 's/[\/&]/\\&/g')"
  escaped_python="$(printf '%s' "$PYTHON_BIN" | sed 's/[\/&]/\\&/g')"
  escaped_user="$(printf '%s' "$user" | sed 's/[\/&]/\\&/g')"

  sed \
    -e "s/__ROOT_DIR__/${escaped_root}/g" \
    -e "s/__PYTHON_BIN__/${escaped_python}/g" \
    -e "s/__SERVICE_USER__/${escaped_user}/g" \
    "$SERVICE_TEMPLATE" | run_cmd tee "$SERVICE_FILE" >/dev/null
}

write_env_defaults() {
  if [[ -f "$ENV_FILE" ]]; then
    return
  fi

  cat > "$ENV_FILE" <<EOF
# 4ham Spectrum Analysis service environment
APP_HOST=127.0.0.1
APP_PORT=8000
FT_EXTERNAL_ENABLE=1
FT_EXTERNAL_MODES=FT8,FT4
DIREWOLF_KISS_ENABLE=1
DIREWOLF_AUTOSTART=1
DIREWOLF_CMD=direwolf -t 0 -p
EOF
}

install_service() {
  ensure_prereqs
  write_service
  write_env_defaults
  run_cmd systemctl daemon-reload
  run_cmd systemctl enable --now "$SERVICE_NAME"
  run_cmd systemctl status "$SERVICE_NAME" --no-pager
}

uninstall_service() {
  run_cmd systemctl disable --now "$SERVICE_NAME" || true
  run_cmd rm -f "$SERVICE_FILE"
  run_cmd systemctl daemon-reload
  echo "Service removed: $SERVICE_NAME"
  echo "Environment file kept: $ENV_FILE (project-local .env)"
}

status_service() {
  run_cmd systemctl status "$SERVICE_NAME" --no-pager
}

logs_service() {
  run_cmd journalctl -u "$SERVICE_NAME" -f --no-pager
}

restart_service() {
  run_cmd systemctl restart "$SERVICE_NAME"
  status_service
}

stop_service() {
  run_cmd systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true
  echo "Service stopped: $SERVICE_NAME"
}

command="${1:-}"
case "$command" in
  install)
    install_service
    ;;
  uninstall)
    uninstall_service
    ;;
  status)
    status_service
    ;;
  logs)
    logs_service
    ;;
  restart)
    restart_service
    ;;
  stop)
    stop_service
    ;;
  *)
    usage
    exit 1
    ;;
esac
