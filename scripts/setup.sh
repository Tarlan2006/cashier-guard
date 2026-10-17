#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
for command in node npm uv ffmpeg ffprobe; do
  command -v "$command" >/dev/null || { echo "Не найден $command. Установите зависимости из README.md."; exit 1; }
done
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (!(major === 22 && minor >= 12 || major >= 24)) { console.error("Нужен Node.js 22.12+ или 24+; Docker использует 24.13.0."); process.exit(1); }'
(cd "$ROOT/backend" && uv sync --frozen --python 3.14.0)
(cd "$ROOT/frontend" && npm ci --no-audit --no-fund)
"$ROOT/backend/.venv/bin/python" - "$ROOT" <<'PY'
from pathlib import Path
import re
import secrets
import sys
from dotenv import dotenv_values

root = Path(sys.argv[1])
target = root / ".env"
content = target.read_text() if target.exists() else (root / ".env.example").read_text()
existing_key = dotenv_values(target).get("API_KEY") if target.exists() else None
if not existing_key or existing_key == "replace-with-your-own-key":
    line = "API_KEY=" + secrets.token_urlsafe(32)
    if re.search(r"^\s*(?:export\s+)?API_KEY\s*=.*$", content, flags=re.MULTILINE):
        content = re.sub(r"^\s*(?:export\s+)?API_KEY\s*=.*$", line, content, flags=re.MULTILINE)
    else:
        content = content.rstrip("\n") + "\n" + line + "\n"
    target.write_text(content)
    print("Создан уникальный API_KEY в .env; значение не выводится. Остальные настройки сохранены.")
else:
    print("Существующий .env и API_KEY сохранены.")
target.chmod(0o600)
PY
echo "Готово. Запуск: ./scripts/dev.sh"
