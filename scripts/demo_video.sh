#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
command -v ffmpeg >/dev/null || { echo "Установите FFmpeg."; exit 1; }
OUTPUT_DIR="${1:-$ROOT/work/demo}"
mkdir -p "$OUTPUT_DIR"
OUTPUT_FILE="$OUTPUT_DIR/SYNTHETIC_cashier_guard_demo_12_seconds.mov"
if [[ -e "$OUTPUT_FILE" ]]; then
  echo "Файл уже существует: $OUTPUT_FILE. Укажите другую выходную папку."
  exit 1
fi
# Only generated colour bars/shapes; no people, cameras, speech or real incidents.
ffmpeg -hide_banner -loglevel error -n \
  -f lavfi -i "testsrc2=size=960x540:rate=24:duration=12" \
  -vf "drawbox=x=360:y=180:w=240:h=180:color=white@0.6:t=fill:enable='between(t,3,5)'" \
  -an -c:v libx264 -preset veryfast -crf 24 -pix_fmt yuv420p \
  -movflags +faststart \
  -metadata title="SYNTHETIC DEMO — generated colour bars, no actual incidents" \
  -metadata comment="Cashier Guard fixture. Demo outcomes are predefined, not inferred from this video." \
  "$OUTPUT_FILE"
echo "Создано синтетическое видео: $OUTPUT_FILE"
echo "Это тестовая таблица и фигуры. Сценарий результата выбирается отдельно в деморежиме."
