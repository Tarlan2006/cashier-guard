#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ! -x "$ROOT/backend/.venv/bin/python" ]]; then
  echo "Сначала выполните ./scripts/setup.sh и подготовку локальных ML из README.md."
  exit 1
fi
exec "$ROOT/backend/.venv/bin/python" "$ROOT/scripts/start_stack.py" "$@"
