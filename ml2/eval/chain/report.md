# Локальный транспорт и matching stub

Дата: 2026-10-18. База: `e196bbd` (отправлен в main с подтверждением пользователя).
Windows, ML Python 3.12.10, backend Python 3.14.7, локальный FFmpeg 9.0.2.
Никакие кадры закрытого набора не читались. Сеть inference ограничена loopback;
скачивание моделей для этой проверки не выполнялось.

## Изменения

- `scripts/matching_stub.py`: отдельная заглушка `/match` на 8002 с явными
  `stub=true` в health и `X-Matching-Stub: true` в успешных ответах.
  Проверяет входной контракт, временные границы, JPEG и каталог. Не выполняет
  семантический matching: копирует только rule_id из формата ML1 adapter ID.
  Поддерживает двоеточия внутри rule_id, неизвестное правило даёт 422.
- `scripts/run_chain.py`, `scripts/run_chain.ps1`: локальный запуск ML1,
  заглушки и настоящего backend, загрузка выбранных открытых видео, polling,
  сохранение JSON и проверка ответа. Ключ случайный, только в памяти и окружении;
  base64 не выводится. Занятые порты не переиспользуются, свои процессы очищаются.
- `scripts/check_events.py`: JSON Schema плюс семантические проверки интервалов,
  уникальности ID наблюдений, вердикта, каталога, декодируемости JPEG и его лимитов.
  Неполный/ошибочный job не принимается за пустой успешный результат.
- `patches/backend-ml-timeouts.patch`: предложение участнику 3; не применено к
  рабочему backend. ML1 read/total=180/190 с, ML2=30/35 с. Общий job deadline,
  обработка ошибок и ограничения файлов не меняются.

Ни один файл `ml2/backend`, конфиг модели, requirements или защищённые директории
`backend/app`, `contracts`, `frontend`, `ml1` этой работой не изменён.
Правила остаются отключёнными. Пустой ML1 означает отсутствие включённых правил,
а не подтверждённую норму на видео.

## Тесты

| Проверка | Результат |
|---|---|
| ML: все unittest, финальный запуск | 177 passed, 9,161 с |
| Backend без патча, полный pytest | 176 passed / 36 failed, 18,43 с |
| Backend с патчем в отдельной копии, полный pytest | 176 passed / 36 failed, 22,04 с |
| Применимость патча | `git apply --check` проходит |
| Новые тесты патча | Раздельные total deadlines и read timeout ML1/ML2 подтверждены |

Одинаковые backend failures воспроизводятся без патча. Причина Windows:
`backend/app/media.py` обращается к отсутствующему `signal.SIGXFSZ`, а обёртка
нормализации импортирует Unix-only `resource` для `RLIMIT_FSIZE`.
Это не регрессия таймаутов. Ограничения диска не обходились, файлы backend
не исправлялись. WSL не установлен, Docker CLI отсутствует.

## Matching через настоящий HTTP 8002

Непустой запрос и JPEG ниже полностью синтетические, это тест транспорта.
Для запроса использован ID из существующей локальной копии каталога команды;
нормативная применимость каталога этой проверкой не утверждается.

| Запрос | HTTP | Результат |
|---|---|---|
| Явный `events: []` | 200 | `no_violation`, 0 событий, stub header |
| Синтетический event с известным rule_id | 200 | `violation`, 1 событие, stub header |
| Event с неизвестным rule_id | 422 | Ошибка, без вердикта |
| Поле events отсутствует | 422 | Ошибка, без вердикта |

## Реальные открытые видео

Использованы открытые видео 2 и 14, настоящий локальный сервис с resident RT-DETR
и SigLIP; кэш детекций между запросами не используется. Прямой POST и запрос
через backend проверяются отдельно. Каталог — явно указанная структурная
транспортная копия существующих материалов команды, не рабочий data/rules.json.

| Видео | Прямой ML1, HTTP / время | events / Rules-Enabled | POST backend | Job / время HTTP-poll |
|---|---|---|---|---|
| 2 | 200 / 21,952 с | [] / none | 202 | failed, PROCESSING_FAILED / 0,366 с |
| 14 | 200 / 57,511 с | [] / none | 202 | failed, PROCESSING_FAILED / 0,529 с |

На обоих прямых ответах `X-Perception-Complete: true`, заголовков неполноты нет.
JSON и события прошли проверку. В backend в обоих случаях стадия `preparing`
завершилась AttributeError; ни analyzing, ни matching не запускались.
Нормализация backend не проверена как работающая, успешного end-to-end вердикта
нет. `run_chain.py` вернул **1**; в отчёте `success=false`, вердикт остался null.
Это ожидаемое обнаружение ошибки среды, а не успешная проверка цепочки.

После завершения сервера 8000/8001/8002 и дочерний worker убраны скриптом;
сторонние процессы не останавливались. Точные JSON и стеки — только в cache.

## Воспроизведение

Из `ml2/`, с уже установленными локальными весами и backend:

```powershell
python scripts/prepare_transport_catalog.py
python scripts/run_chain.py --open-root DATA_OPEN --models MODEL_ROOT --ffmpeg-bin FFMPEG_BIN --rules-path cache/integration/transport_catalog.json --videos 2 14 --direct-ml1 --expect-empty
python scripts/check_events.py cache/chain/RUN/02.ml1.json --kind ml1 --expect-empty
python scripts/check_events.py cache/chain/RUN/02.job.json --kind job --expect-empty
```

`DATA_OPEN` должен быть разрешённым `data/open`. Для Linux backend можно использовать
тот же Python-скрипт; Windows PS1 — только удобная обёртка. Текущий полный запуск
на Windows ожидаемо не пройдёт до исправления backend участником 3.
Последняя команда отвергает failed job с ненулевым кодом, не маскирует ошибку.
Сырые ответы и логи этой сессии остаются только в игнорируемом
`cache/chain_validation/`, видео и веса в git не добавлены.
