#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ! -x "$ROOT/backend/.venv/bin/python" || ! -d "$ROOT/frontend/node_modules" || ! -f "$ROOT/.env" ]]; then
  echo "Сначала запустите ./scripts/setup.sh"
  exit 1
fi
# Fixed ports match frontend/vite.config.ts. Refuse to display a stale running app.
"$ROOT/backend/.venv/bin/python" - <<'PY'
import socket
import sys
for port in (8000, 5173):
    with socket.socket() as sock:
        # A recently stopped server may leave sockets in TIME_WAIT.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            sys.exit(f"Порт {port} занят. Остановите предыдущий процесс перед запуском.")
PY
BACKEND_PID=""
FRONTEND_PID=""
cleanup() {
  for pid in "$BACKEND_PID" "$FRONTEND_PID"; do
    if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null || true; fi
  done
  for pid in "$BACKEND_PID" "$FRONTEND_PID"; do
    if [[ -n "$pid" ]]; then wait "$pid" 2>/dev/null || true; fi
  done
}
trap cleanup EXIT
trap 'exit 0' INT TERM
(cd "$ROOT/backend" && exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log) &
BACKEND_PID=$!
(cd "$ROOT/frontend" && exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort) &
FRONTEND_PID=$!
echo "Сайт: http://127.0.0.1:5173 · API: http://127.0.0.1:8000/docs"
echo "Ключ доступа: API_KEY в корневом .env; в вывод он не включён."
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do sleep 1; done
echo "Один из процессов завершился. Проверьте сообщение выше."
exit 1
