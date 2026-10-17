# Контракты интеграции, версия 1.0

Владелец: участник 3 вместе с ML1 и ML2. Изменения формата согласовываем до merge.

```text
Frontend → POST /api/v1/analyze → очередь backend
                                     ↓
                           ML1 POST /analyze
                                     ↓ события + JPEG
data/rules.json ───────────→ ML2 POST /match
                                     ↓ вердикт + rule_id
Frontend ← GET /api/v1/jobs/{job_id} ← backend + проверенный источник
```

Источник типов: `backend/app/models.py`. JSON Schema генерируются `scripts/export_contracts.py`.
Генерация: из корня `backend/.venv/bin/python scripts/export_contracts.py`.
OpenAPI: `/openapi.json`; интерактивная документация: `/docs`.

## API для пользователя и жюри

Все запросы анализа и получения результатов требуют `X-API-Key`.
`GET /api/v1/health` доступен без ключа и сообщает режим и лимит размера.

`POST /api/v1/analyze`: multipart `file` (MOV обязателен, MP4 также поддерживается).
Необязательное поле `demo_scenario`: `violation` (по умолчанию) или `no_violation`.
Поле работает только в demo; в live результат определяется ML-модулями.

HTTP 202:

```json
{"job_id":"<id>","status":"processing","mode":"demo"}
```

`GET /api/v1/jobs/{job_id}`: `status` — `processing`, `done` или `failed`.
`stage` уточняет статус: `queued`, `preparing`, `analyzing`, `matching`, `done`, `failed`.
Только при `done` есть `verdict: violation | no_violation` и окончательный список `violations`.
Ошибка обработки возвращается как `status: failed` с понятным полем `error`, без выдуманного вердикта.

Каждое событие содержит обязательные поля кейса: `type`, `timecode_sec`, `description`,
`evidence_frames: [{timestamp_sec, image_base64}]`. Дополнительно возвращаются `rule_id`, `rule`.
Все таймкоды — неотрицательные секунды от начала видео. JPEG передаётся без префикса data URL.

Коды ошибок: 400 пустой файл; 401 ключ; 404 неизвестная задача; 413 размер; 415 расширение;
422 неверная форма запроса; 503 заполненная очередь. Повреждённое видео даёт задачу со статусом `failed`.

## Demo и live

В demo событие генерируется заглушкой и не зависит от содержимого ролика. Кадр извлекается FFmpeg
из загруженного видео. `rule` отсутствует, поскольку нормативы не выдумываются.
Клиент должен показывать деморежим и не представлять такой результат как реальное обнаружение.

В live backend отправляет видео в ML1, затем кадры и правила в ML2. Он валидирует JSON,
согласованность вердикта, диапазон времени, наличие JPEG и `rule_id` в каталоге.
Эти проверки проверяют структуру, но не заменяют оценку качества и подлинности доказательств участником 4.

