#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ! -x "$ROOT/backend/.venv/bin/python" || ! -d "$ROOT/frontend/node_modules" || ! -f "$ROOT/.env" ]]; then
  echo "Сначала запустите ./scripts/setup.sh"
  exit 1
fi
(cd "$ROOT/backend" && exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
BACKEND_PID=$!
(cd "$ROOT/frontend" && exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173) &
FRONTEND_PID=$!
cleanup() { kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true; wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 0' INT TERM
echo "Сайт: http://127.0.0.1:5173 · API: http://127.0.0.1:8000/docs"
echo "Ключ доступа: API_KEY в $ROOT/.env"
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do sleep 1; done
exit 1

