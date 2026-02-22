#!/usr/bin/env bash
# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 01:13:28 UTC

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
LOG_DIR="$ROOT_DIR/logs"
LOG_FILE="$LOG_DIR/backend.log"
PID_FILE="$LOG_DIR/backend.pid"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"

usage() {
  echo "Usage: $(basename "$0") {start|stop|logs|status}"
}

export WSJTX_UDP_ENABLE="${WSJTX_UDP_ENABLE:-1}"
export WSJTX_AUTOSTART="${WSJTX_AUTOSTART:-1}"
export WSJTX_CMD="${WSJTX_CMD:-wsjtx}"
export DIREWOLF_KISS_ENABLE="${DIREWOLF_KISS_ENABLE:-1}"
export DIREWOLF_AUTOSTART="${DIREWOLF_AUTOSTART:-1}"
export DIREWOLF_CMD="${DIREWOLF_CMD:-direwolf -t 0 -p}"

ensure_environment() {
  mkdir -p "$LOG_DIR"
  python3 -m venv "$ROOT_DIR/.venv" >/dev/null 2>&1 || true
  "$PYTHON_BIN" -m pip install -r "$BACKEND_DIR/requirements.txt" >/dev/null
}

start_backend() {
  ensure_environment
  pkill -f 'uvicorn app.main:app' >/dev/null 2>&1 || true
  sleep 1
  local reload_args=()
  if [[ "${RUN_DEV_RELOAD:-0}" == "1" ]]; then
    reload_args=(--reload --reload-dir "$BACKEND_DIR")
  fi
  nohup "$PYTHON_BIN" -m uvicorn app.main:app --app-dir "$BACKEND_DIR" --host 127.0.0.1 --port 8000 "${reload_args[@]}" >>"$LOG_FILE" 2>&1 &
  local pid="$!"
  echo "$pid" > "$PID_FILE"
  echo "Backend started (PID: $pid)"
  if [[ "${RUN_DEV_RELOAD:-0}" == "1" ]]; then
    echo "Mode: reload enabled"
  else
    echo "Mode: stable (no reload)"
  fi
  echo "Log file: $LOG_FILE"
}

stop_backend() {
  pkill -f 'uvicorn app.main:app' >/dev/null 2>&1 || true
  rm -f "$PID_FILE"
  echo "Backend stopped"
}

show_logs() {
  mkdir -p "$LOG_DIR"
  touch "$LOG_FILE"
  tail -f "$LOG_FILE"
}

show_status() {
  echo "=== Backend status ==="
  local pids
  pids="$(pgrep -af 'uvicorn app.main:app' || true)"
  if [[ -n "$pids" ]]; then
    echo "$pids"
  else
    echo "No uvicorn process found"
  fi

  echo
  echo "=== Port 8000 ==="
  ss -ltnp | grep ':8000' || echo "Port 8000 is not listening"

  echo
  echo "=== API health (/api/scan/status) ==="
  curl -s -m 3 http://127.0.0.1:8000/api/scan/status || echo "API not responding"

  echo
  echo "=== Log tail ==="
  mkdir -p "$LOG_DIR"
  touch "$LOG_FILE"
  tail -n 20 "$LOG_FILE"
}

command="${1:-start}"

case "$command" in
  start)
    start_backend
    ;;
  stop)
    stop_backend
    ;;
  logs)
    show_logs
    ;;
  status)
    show_status
    ;;
  *)
    usage
    exit 1
    ;;
esac
