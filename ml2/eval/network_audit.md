# Аудит сетевых вызовов

Дата: 2026-10-18. База: main `8372756`; также проверен новый скрипт
`scripts/robustness_check.py`. Логика, зависимости и конфиги не менялись.
Проверены ml2/service, ml2/backend, ml2/scripts и backend/app.
download_models.py исключён из поиска runtime по заданию: это явно запускаемая
подготовка весов с HTTPS к закреплённым revision на huggingface.co, не обработчик API.

## Метод статической проверки

```powershell
rg -n -i 'requests|httpx|urllib|aiohttp|socket|huggingface_hub|from_pretrained|openai|anthropic|gemini|google\.generativeai' ml2/service ml2/backend ml2/scripts backend/app -g '*.py' -g '!download_models.py'
```

Дополнительно искались URL, connect/open_connection, загрузчики torch.hub,
snapshot_download, telemetry, subprocess. AST-проверка нашла 11 вызовов
from_pretrained: у каждого явно local_files_only=True. Облачных AI SDK,
requests/aiohttp или прямого huggingface_hub в проверяемом коде нет.
Упоминания библиотеки в транзитивных зависимостях не равны её вызову.

| Файл:строка | Вызов / совпадение | Когда и куда | Вывод |
|---|---|---|---|
| ml2/service/app.py:15–20 | os.environ.update | При импорте сервиса, до импорта pipeline | HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1, HF_HUB_DISABLE_TELEMETRY=1, DO_NOT_TRACK=1 |
| ml2/backend/pipeline/perception/torch_detector.py:60,64 | processor/model.from_pretrained | Альтернативный PyTorch backend при загрузке локальных моделей | Оба local_files_only=True; default ONNX не требует этих вызовов |
| ml2/backend/pipeline/perception/depth.py:13–14,25–26 | offline env, processor/model.from_pretrained | Только опциональный эксперимент глубины | Оба local_files_only=True; при стандартном старте не загружается |
| ml2/scripts/export_perception_onnx.py:28–30,143,148,155 | offline env, config/model/processor.from_pretrained | Явный локальный экспорт RT-DETR при подготовке | Все три local_files_only=True, не обработчик запроса |
| ml2/scripts/export_siglip_zeroshot.py:25–27,123,208 | offline env, model/processor.from_pretrained | Явный локальный экспорт SigLIP | Оба local_files_only=True, не обработчик запроса |
| ml2/scripts/export_scene_text.py:11–13,28 | offline env, text model.from_pretrained | Подготовка текстовых признаков | local_files_only=True |
| ml2/scripts/export_local_prompts.py:11–12,27 | offline env, text model.from_pretrained | Подготовка текстовых признаков | local_files_only=True |
| backend/app/pipeline.py:9,61–87,188–198 | httpx.AsyncClient / stream POST; аннотации, except | На live-запросе: ML1_URL/analyze и ML2_URL/match | Локальный транспорт ML, не облачный AI; trust_env=False, follow_redirects=False |
| backend/app/config.py:19–20 | ML1_URL / ML2_URL | Адреса настраиваются окружением, default 127.0.0.1:8001/8002 | Код не ограничивает адреса loopback: при развёртывании нужно сохранить локальные URL |
| backend/app/readiness.py:3,23–29 | urllib.parse.urlparse; asyncio.open_connection | /ready в live: TCP к двум настроенным ML URL | Парсинг локален; TCP-проверка доступности, не AI API |
| backend/app/models.py:7 | urllib.parse.urlsplit | Валидация ссылок на источники правил | Парсинг строки; ссылки не запрашиваются |
| ml2/scripts/check_events.py:11 | urllib.parse.urlsplit | Локальная валидация JSON/ссылок | Нет запроса по URL |
| ml2/scripts/integration_check.py:13,23–31,131–201 | httpx.Client, GET/POST, аннотации/except | Только явно запущенная проверка; hardcoded 127.0.0.1:8000/8001/8002 | Локальные health/analyze/jobs, trust_env=False |
| ml2/scripts/run_chain.py:14,55–59 | socket.socket, setsockopt, bind | Проверка свободных портов перед запуском | Только bind 127.0.0.1, не исходящее соединение |
| ml2/scripts/run_chain.py:19,108–139,184–208,249–254 | httpx, GET/POST, аннотации/except | Явный запуск цепочки; 127.0.0.1, настраиваются только номера портов | Локальный транспорт, trust_env=False, redirects=False |
| ml2/scripts/launch_chain.py:15,75–90,142,159–163,189 | httpx; URL для контейнера | Явный launcher; клиентские запросы к 127.0.0.1; контейнерный backend к host.docker.internal | Адрес хоста Docker — локальная межпроцессная связь; не AI cloud |
| ml2/scripts/launch_chain.py:30,136,157 | docker info / image inspect / run | Подготовка/запуск launcher | run использует --pull never; установка образа — отдельная операция, не анализ |
| ml2/scripts/robustness_check.py:17,19,35–45,54–80,122–127 | urllib.parse, httpx.Client / GET/POST, аннотации/except | Новый явный тест; разрешён только HTTP с loopback IP | Внешний адрес, credentials, query и redirects отклоняются; proxy env отключён |
| ml2/backend/pipeline/video.py:93–95 | av.open | На запросе читает существующий локальный файл | protocol_whitelist=file; аудио не декодируется |
| backend/app/media.py:67–73 | параметры FFmpeg/FFprobe | Нормализация локального видео на запросе | file protocol whitelist, MOV drefs/absolute references отключены |
| ml2/service/app.py:128; ml2/backend/pipeline/analysis_worker.py:97; resident.py:1; video.py:198 | Слово requests в строке/докстринге | Заголовок о кэше, документация IPC/PTS | Ложные текстовые совпадения, не вызовы requests |
| backend/app/media.py:69; middleware.py:29 | requests/socket в комментарии | Описание защиты демультиплексора и обработки разрыва соединения | Ложные текстовые совпадения |

Экспортные scripts вызываются download_models.py только при явном --download;
обычный service.app их не запускает. get_detector/default ONNX и SigLIP ONNX
читают локальные графы/NPZ. Исключение download_models.py не скрывает runtime-вызов:
проверено отсутствие его импорта/запуска из service и backend/pipeline.

## Динамическая проверка Windows

Настоящий Uvicorn service.app на 127.0.0.1:8001, один resident worker, CPU.
Веса — существующий локальный комплект; скачивание не выполнялось.
psutil отсутствует, поэтому использованы штатные Windows-команды:
Get-CimInstance Win32_Process для дерева PID, Get-NetTCPConnection и
Get-NetUDPEndpoint с фильтром OwningProcess. Снимки включают дочерний inference,
а не только принимающий HTTP процесс. Ошибок доступа к таблицам сокетов нет.

| Показатель | Результат |
|---|---|
| PID сервера / inference | 8284 / 15012 |
| Запрос | Один POST /analyze, только data/open, видео 2 |
| Offline-переменные фактически в процессе | Все четыре перечисленные выше равны 1; spawn наследует окружение |
| /health | 200, local_only=true, no_rules; detector_loads=1, vision_encoder_loads=1 |
| Ответ анализа | 200, schema_version=1.0, events=[], X-Rules-Enabled=none, X-Perception-Complete=true |
| Время | X-Elapsed-Seconds=34.200; весь прогон со съёмом сокетов 35.763 с |
| Снимки | 13, от 3.501 до 35.248 с от начала проверки |
| TCP | 65 записей суммарно, 5 на снимок; Listen/Established только 127.0.0.1 |
| Bound | Дополнительно unconnected 0.0.0.0:4731 → 0.0.0.0:0; это не удалённое соединение |
| Inference worker | В снимках нет TCP/UDP endpoints |
| UDP | 0 endpoints |
| Внешние удалённые адреса | Не обнаружены |

В наблюдавшемся анализе обращений к внешней сети/облачным AI API нет.
Снимки не являются packet capture: короткое соединение между опросами могло
не попасть в таблицу. Проверка не охватывает системные службы телеметрии ОС,
все возможные сторонние сборки библиотек или изменённые конфиги развёртывания.
Исходные логи/JSON остаются во временной папке вне Git; кадров в отчёте нет.
