#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "${FRONTEND_PID:-}" ]]; then
    kill "$FRONTEND_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

python3 -m venv "$ROOT_DIR/.venv" >/dev/null 2>&1 || true
source "$ROOT_DIR/.venv/bin/activate"

pip install -r "$BACKEND_DIR/requirements.txt"

uvicorn app.main:app --reload --app-dir "$BACKEND_DIR" &
BACKEND_PID=$!

python3 -m http.server 5173 --directory "$FRONTEND_DIR" &
FRONTEND_PID=$!

wait
