#!/usr/bin/env bash
# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
#
# 4ham-spectrum-analysis — server control (manual install mode)
#
# Usage:
#   ./scripts/server_control.sh start
#   ./scripts/server_control.sh stop
#   ./scripts/server_control.sh restart
#   ./scripts/server_control.sh status
#   ./scripts/server_control.sh logs

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
LOG_DIR="$ROOT_DIR/logs"
LOG_FILE="$LOG_DIR/backend.log"
PID_FILE="$LOG_DIR/backend.pid"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"

usage() {
  cat <<EOF
Usage: $(basename "$0") {start|stop|restart|status|logs}

  start    Start the backend server in the background
  stop     Stop the backend server (and managed decoders)
  restart  Stop then start
  status   Show running processes and API health
  logs     Tail the live log file (Ctrl+C to exit)
EOF
}

# ── helpers ────────────────────────────────────────────────────────────────────

collect_uvicorn_pids() {
  pgrep -f 'uvicorn app.main:app' 2>/dev/null || true
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
import os, signal, time

TARGET_KEYS = ("FOURHAM_MANAGED=1", "FOURHAM_MANAGED_BY=4ham-spectrum-analysis")

def iter_managed_pids():
    for name in os.listdir('/proc'):
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            with open(f'/proc/{pid}/environ', 'rb') as f:
                env = f.read().decode('utf-8', errors='ignore')
            with open(f'/proc/{pid}/cmdline', 'rb') as f:
                cmdline = f.read().decode('utf-8', errors='ignore').replace('\x00', ' ')
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if all(k in env for k in TARGET_KEYS) and 'direwolf' in cmdline.lower():
            yield pid

managed = sorted(set(iter_managed_pids()))
for pid in managed:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

deadline = time.time() + 4.0
while managed and time.time() < deadline:
    managed = [p for p in managed if os.path.exists(f'/proc/{p}')]
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

# ── guard: require the installer to have completed ─────────────────────────────
check_installation() {
  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Error: Python virtual environment not found at $ROOT_DIR/.venv" >&2
    echo "       Run the installer first: ./install.sh" >&2
    exit 1
  fi
}

# ── commands ───────────────────────────────────────────────────────────────────

do_start() {
  check_installation

  local existing_pids
  existing_pids="$(collect_uvicorn_pids)"
  if [[ -n "$existing_pids" ]]; then
    echo "Server is already running (PID: $(echo "$existing_pids" | tr '\n' ' '))"
    exit 0
  fi

  mkdir -p "$LOG_DIR"

  local env_args=()
  if [[ -f "$ROOT_DIR/.env" ]]; then
    env_args=(--env-file "$ROOT_DIR/.env")
  fi

  # Run from ROOT_DIR so relative paths (data/, config/, etc.) resolve correctly.
  cd "$ROOT_DIR"
  nohup "$PYTHON_BIN" -m uvicorn app.main:app \
    --app-dir "$BACKEND_DIR" \
    --host 0.0.0.0 \
    --port 8000 \
    "${env_args[@]}" \
    >> "$LOG_FILE" 2>&1 &
  local pid="$!"
  echo "$pid" > "$PID_FILE"
  echo "Server started (PID: $pid)"
  echo "Log : $LOG_FILE"
  echo "URL : http://127.0.0.1:8000/"
}

do_stop() {
  check_installation

  local pids
  pids="$(collect_uvicorn_pids)"
  if [[ -z "$pids" ]]; then
    echo "Server is not running."
    rm -f "$PID_FILE"
    return 0
  fi

  echo "Stopping server (PID: $(echo "$pids" | tr '\n' ' '))..."
  for pid in $pids; do
    kill_process_tree "$pid"
  done
  wait_for_shutdown
  stop_managed_decoder_processes
  rm -f "$PID_FILE"
  echo "Server stopped."
}

do_restart() {
  do_stop
  sleep 0.5
  do_start
}

do_status() {
  echo "=== Server processes ==="
  local pids
  pids="$(pgrep -af 'uvicorn app.main:app' 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "$pids"
  else
    echo "No server process found."
  fi

  echo
  echo "=== Port 8000 ==="
  ss -ltnp 2>/dev/null | grep ':8000' || echo "Port 8000 is not listening."

  echo
  echo "=== API health ==="
  curl -s -m 3 http://127.0.0.1:8000/api/scan/status 2>/dev/null || echo "API not responding."

  echo
  echo "=== Last 20 log lines ==="
  if [[ -f "$LOG_FILE" ]]; then
    tail -n 20 "$LOG_FILE"
  else
    echo "No log file found at $LOG_FILE"
  fi
}

do_logs() {
  mkdir -p "$LOG_DIR"
  touch "$LOG_FILE"
  echo "Tailing $LOG_FILE  (Ctrl+C to exit)"
  tail -f "$LOG_FILE"
}

# ── dispatch ───────────────────────────────────────────────────────────────────

command="${1:-}"

case "$command" in
  start)    do_start ;;
  stop)     do_stop ;;
  restart)  do_restart ;;
  status)   do_status ;;
  logs)     do_logs ;;
  -h|--help|help) usage ;;
  *)
    echo "Error: unknown command '${command}'" >&2
    usage
    exit 1
    ;;
esac
