#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

python3 -m venv "$ROOT_DIR/.venv" >/dev/null 2>&1 || true
source "$ROOT_DIR/.venv/bin/activate"

pip install -r "$BACKEND_DIR/requirements.txt"

export WSJTX_UDP_ENABLE="${WSJTX_UDP_ENABLE:-1}"
export WSJTX_AUTOSTART="${WSJTX_AUTOSTART:-1}"
export WSJTX_CMD="${WSJTX_CMD:-wsjtx}"
export DIREWOLF_KISS_ENABLE="${DIREWOLF_KISS_ENABLE:-1}"
export DIREWOLF_AUTOSTART="${DIREWOLF_AUTOSTART:-1}"
export DIREWOLF_CMD="${DIREWOLF_CMD:-direwolf -t 0 -p}"

uvicorn app.main:app --reload --app-dir "$BACKEND_DIR" --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

wait
