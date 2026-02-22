#!/usr/bin/env bash
# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 16:27:19 UTC

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

collect_uvicorn_pids() {
  pgrep -f 'uvicorn app.main:app' || true
}

kill_process_tree() {
  local parent_pid="$1"
  local child
  for child in $(pgrep -P "$parent_pid" 2>/dev/null || true); do
    kill_process_tree "$child"
  done
  kill -TERM "$parent_pid" >/dev/null 2>&1 || true
}

stop_managed_decoder_processes() {
  "$PYTHON_BIN" - <<'PY'
import os
import signal
import time

TARGET_KEYS = ("FOURHAM_MANAGED=1", "FOURHAM_MANAGED_BY=4ham-spectrum-analysis")

def iter_managed_pids():
    for name in os.listdir('/proc'):
        if not name.isdigit():
            continue
        pid = int(name)
        environ_path = f'/proc/{pid}/environ'
        cmdline_path = f'/proc/{pid}/cmdline'
        try:
            with open(environ_path, 'rb') as f:
                env = f.read().decode('utf-8', errors='ignore')
            with open(cmdline_path, 'rb') as f:
                cmdline = f.read().decode('utf-8', errors='ignore').replace('\x00', ' ')
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if all(key in env for key in TARGET_KEYS) and ('wsjtx' in cmdline.lower() or 'direwolf' in cmdline.lower()):
            yield pid

managed = sorted(set(iter_managed_pids()))
for pid in managed:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

deadline = time.time() + 4.0
while managed and time.time() < deadline:
    managed = [pid for pid in managed if os.path.exists(f'/proc/{pid}')]
    if managed:
        time.sleep(0.15)

for pid in managed:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
PY
}

wait_for_shutdown() {
  local deadline=$((SECONDS + 8))
  while true; do
    local pids
    pids="$(collect_uvicorn_pids)"
    if [[ -z "$pids" ]]; then
      break
    fi
    if (( SECONDS >= deadline )); then
      for pid in $pids; do
        kill -KILL "$pid" >/dev/null 2>&1 || true
      done
      break
    fi
    sleep 0.2
  done
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
  stop_backend >/dev/null 2>&1 || true
  sleep 0.5
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
  local pids
  pids="$(collect_uvicorn_pids)"
  if [[ -n "$pids" ]]; then
    for pid in $pids; do
      kill_process_tree "$pid"
    done
  fi
  wait_for_shutdown
  stop_managed_decoder_processes
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
