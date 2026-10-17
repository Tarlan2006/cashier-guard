#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
for command in node npm uv ffmpeg ffprobe; do
  command -v "$command" >/dev/null || { echo "Не найден $command. Установите зависимости из README.md."; exit 1; }
done
(cd "$ROOT/backend" && uv sync)
(cd "$ROOT/frontend" && npm ci --no-audit --no-fund)
"$ROOT/backend/.venv/bin/python" - "$ROOT" <<'PY'
from pathlib import Path
import secrets
import sys
root = Path(sys.argv[1])
target = root / '.env'
if not target.exists():
    content = (root / '.env.example').read_text().replace('replace-with-your-own-key', secrets.token_urlsafe(32))
    target.write_text(content)
    target.chmod(0o600)
    print('Создан .env с уникальным API_KEY. Скопируйте ключ в поле интерфейса.')
else:
    print('Существующий .env сохранён.')
PY
echo "Готово. Запуск: ./scripts/dev.sh"

