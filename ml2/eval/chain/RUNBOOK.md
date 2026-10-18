# Запуск трёх сервисов для жюри

Дата: 2026-10-18. База: `3042ed7`. Команды ниже выполняются из корня cashier-guard.
После однократной подготовки три сервиса запускает **один скрипт**
`ml2/scripts/launch_chain.py`. Логика анализа и каталог этим скриптом не меняются.

Обновление после `8cf0d4c`: патч таймаутов **уже применён в main**.
`ml2/patches/backend-ml-timeouts.patch` оставлен для истории и обратной проверки.
Команды ниже используют только `git apply --reverse --check`, без отмены патча.
Launcher и build-скрипт распознают готовое состояние (`timeouts already applied`);
повторного применения нет. Несовместимое состояние останавливает запуск.

## Историческая проверка Linux runtime и текущий маршрут launcher

Таблица ниже относится к проверке на базе `3042ed7`. Windows-совместимость
backend исправлена в `20d3f21` (актуально 217 passed), но выбор runtime
в launcher этой правкой не менялся: Windows по-прежнему использует Docker.

На текущем Windows `wsl --status` вернул код **50**:
`The Windows Subsystem for Linux is not installed.`
`docker --version` выполнить нельзя: docker отсутствует в PATH; стандартные
файлы Docker Desktop также не найдены. Установка/эмуляция не предпринимались.

| Видео | Вердикт с Linux backend и новым патчем | События | Время | Статус |
|---|---|---|---|---|
| 2 | Не получен | Не измерено | Не измерено | BLOCKED: нет Linux runtime |
| 14 | Не получен | Не измерено | Не измерено | BLOCKED: нет Linux runtime |

Нужен **один** вариант: Docker Desktop с Linux engine; WSL2 с Linux,
Python/зависимостями backend и FFmpeg; либо Linux-машина.
Windows-путь ниже использует Docker Desktop. WSL2 без Docker позволяет запустить
Linux-путь внутри дистрибутива, если все три сервиса и веса установлены в нём;
гибрид Windows ML + WSL backend в этой сессии не проверялся.
Docker build, Linux runtime и связь контейнер→хост здесь **не испытаны**.
Скрипт без Docker завершится до запуска моделей, а не подменит backend заглушкой.
Исторические HTTP-замеры Windows ML1: [report.md](report.md); они не являются
успешной проверкой Linux backend или новых таймаутов.

## Схема, порты и ключ

| Компонент | Адрес для пользователя | Health | Назначение |
|---|---|---|---|
| backend | `http://127.0.0.1:8000` | `/api/v1/health`, `/api/v1/ready` | Загрузка, нормализация, очередь, результат |
| наш ML1 из ml2 | `http://127.0.0.1:8001` | `/health` | Локальный анализ видео |
| matching **STUB** | `http://127.0.0.1:8002` | `/health` | Только проверка транспорта и копирование явного rule_id |

backend всегда `PIPELINE_MODE=live`, `WORKERS=1`. Matching — заглушка, не реальная
проверка норм. Правила распознавания пока отключены: ML1 возвращает events=[],
matching — no_violation. Это отсутствие включённых правил, не доказанная норма.
Закрытые видео не нужны для подготовки или проверки запуска; автоматический
тестовый режим принимает только открытый `data/open`.

`API_KEY` задайте в окружении своего терминала. Скрипт не печатает и не сохраняет
его; backend требует `X-API-Key` на загрузке и чтении job. Health доступен без ключа.
Модельные веса, ответы с JPEG, логи и хранилище не попадают в Git.

## Windows: ML на хосте, backend в Linux-контейнере

1. Установите/запустите Docker Desktop в режиме **Linux containers**.
   Используйте локальный Docker context, не удалённый daemon/builder.
   До продолжения `docker --version` и `docker info --format '{{.OSType}}'`
   должны работать; вторая команда должна вывести `linux`.
2. Однократно подготовьте ML Python 3.12 и веса. Сеть нужна только на подготовке:

```powershell
py -3.12 -m venv ml2/.venv
& ./ml2/.venv/Scripts/python.exe -m pip install -r ml2/requirements.txt
$env:ML_MODELS_DIR = 'D:/local-models'
& ./ml2/.venv/Scripts/python.exe ml2/scripts/download_models.py --source $env:ML_MODELS_DIR --verify-only
```

В `ML_MODELS_DIR` уже должны находиться `rtdetr_r18vd/` и
`siglip-base-patch16-224/`. Подготовка весов: [README](../../README.md#запуск).
Depth-модель для сервиса не нужна.

3. Подготовьте каталог и backend image:

```powershell
# Для теста транспорта: структурная копия имеющегося каталога команды.
# Для настоящего matching потребуется утверждённый каталог участника 4.
& ./ml2/.venv/Scripts/python.exe ml2/scripts/prepare_transport_catalog.py
git apply --reverse --check ml2/patches/backend-ml-timeouts.patch
docker build -f ml2/docker/backend.Dockerfile -t cashier-guard-backend-ml2:timeouts-v2 .
```

Dockerfile устанавливает зависимости из backend lockfile и FFmpeg, проверяет
состояние патча и значения ML1=180/190, ML2=90/100. В текущем main патч уже
применён: build пишет `timeouts already applied`. Только для старого checkout
патч применяется к файлам image; если не подходит ни прямая, ни обратная
проверка, сборка останавливается с ошибкой.
Рабочий `backend/app` не редактируется. Dockerfile-specific dockerignore
разрешает только исходники backend, lockfile, contract fixtures и патч;
данные, видео, `.env`, cache, модели и ключи в image/context не включаются.
Image должен быть собран заранее: при запуске используется `--pull never`.

4. Задайте ключ в окружении, затем одной командой запустите всё:

```powershell
$env:API_KEY = & ./ml2/.venv/Scripts/python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
& ./ml2/.venv/Scripts/python.exe ml2/scripts/launch_chain.py --runtime docker --models $env:ML_MODELS_DIR --rules-path ml2/cache/integration/transport_catalog.json
```

ML1 и matching запускаются на Windows, слушают `0.0.0.0:8001/8002` для доступа
контейнера; разрешите этот доступ в firewall для локальной Docker-сети.
В **окружение контейнера** передаются:

```text
ML1_URL=http://host.docker.internal:8001
ML2_URL=http://host.docker.internal:8002
RULES_PATH=/app/catalog.json
STORAGE_DIR=/app/storage
PIPELINE_MODE=live
WORKERS=1
API_KEY=(из окружения, без вывода значения)
```

`localhost` внутри контейнера означает сам контейнер, поэтому ML1_URL/ML2_URL
должны указывать на Windows-хост. Docker Desktop предоставляет имя
[host.docker.internal](https://docs.docker.com/desktop/features/networking/networking-how-tos/).
Каталог монтируется read-only, storage — в отдельную папку `ml2/cache/jury/`.
backend публикуется только на `127.0.0.1:8000`; Docker image не содержит моделей.

## Linux: три локальных процесса

1. Нужны Python 3.12 для ML, Python 3.14 для backend, Git, FFmpeg/ffprobe,
   uv 0.12.18. Docker не требуется. Подготовьте окружения и локальные веса:

```bash
python3.12 -m venv ml2/.venv
ml2/.venv/bin/python -m pip install -r ml2/requirements.txt
uv sync --project backend --python python3.14 --frozen --no-dev --no-install-project
export ML_MODELS_DIR=/path/to/local-models
ml2/.venv/bin/python ml2/scripts/download_models.py --source "$ML_MODELS_DIR" --verify-only
ml2/.venv/bin/python ml2/scripts/prepare_transport_catalog.py
git apply --reverse --check ml2/patches/backend-ml-timeouts.patch
```

2. Задайте ключ и запустите всё одной командой:

```bash
export API_KEY="$(ml2/.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
ml2/.venv/bin/python ml2/scripts/launch_chain.py --runtime native --models "$ML_MODELS_DIR" --rules-path ml2/cache/integration/transport_catalog.json
```

Все три процесса слушают loopback. `ML1_URL=http://127.0.0.1:8001`,
`ML2_URL=http://127.0.0.1:8002`. В текущем main backend запускается без изменения
файлов из `backend/`, с сообщением `timeouts already applied`. Только для старого
checkout создаётся `ml2/cache/jury/RUN/source/backend` и патч применяется к этой
копии. Зависимости берутся из `backend/.venv/bin/python`.
Можно указать другой `--backend-python PYTHON`.
Репозиторный `backend/app` не меняется, файловые ограничения не отключаются.

## Проверка health и тест видео 2/14

Launcher сам проверяет **три health** и `/api/v1/ready`, включая доступность ML
именно из backend. При успехе печатает `ready: true`, порты и адреса ML, без ключа.
Readiness не доказывает качество распознавания. Дополнительные проверки из терминала:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health
Invoke-RestMethod http://127.0.0.1:8002/health
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
Invoke-RestMethod http://127.0.0.1:8000/api/v1/ready
```

На Linux те же адреса проверяются `curl --fail --silent --show-error URL`.
Matching health должен содержать `stub: true`. Для загрузки видео через curl
заголовок обязателен; используйте терминал, в котором задан API_KEY:

Для ручного сценария заранее задайте один и тот же известный вам ключ в окружении
серверного и клиентского терминалов; новая вкладка не наследует изменения окружения
другой вкладки. Случайная генерация выше удобна для автоматического POST внутри launcher.

Windows (отдельный клиентский терминал с тем же API_KEY):

```powershell
curl.exe --fail --silent --show-error -H "X-API-Key: $env:API_KEY" -F "file=@D:/data/open/videos/X-2.mov" http://127.0.0.1:8000/api/v1/analyze
curl.exe --fail --silent --show-error -H "X-API-Key: $env:API_KEY" http://127.0.0.1:8000/api/v1/jobs/JOB_ID
```

Linux:

```bash
curl --fail --silent --show-error -H "X-API-Key: $API_KEY" -F "file=@/path/to/data/open/videos/X-2.mov" http://127.0.0.1:8000/api/v1/analyze
# Из ответа 202 возьмите job_id; повторяйте GET до done/failed:
curl --fail --silent --show-error -H "X-API-Key: $API_KEY" http://127.0.0.1:8000/api/v1/jobs/JOB_ID
```

Для полностью автоматического прогона сначала остановите обычный launcher
через Ctrl+C. Запустите его же с `--open-root /path/to/data/open --videos 2 14
--expect-empty` (на Windows используйте PowerShell-команду выше с этими аргументами).
Он поднимет сервисы, вызовет **POST /api/v1/analyze**, опросит jobs, проверит
контракт/кадры и выведет таблицу данных в JSON: video, verdict, events, wall_sec,
status, error_code. Сохранит ответы в `cache/jury/RUN/NN.job.json` и report.json,
после теста остановит только собственные процессы и свой контейнер.
Код 0 — проверки прошли; код 1 — ошибка, failed или неполный ответ.
Для отдельной проверки JSON: `python ml2/scripts/check_events.py PATH --kind job
--rules-path ml2/cache/integration/transport_catalog.json --expect-empty`.

Ctrl+C в обычном режиме также останавливает собственные процессы и контейнер.
Ключ остаётся только в окружении терминала/процессов; runtime не создаёт `.env`.

## Таймауты и диагностика

| Стадия | read | Полный HTTP-запрос |
|---|---:|---:|
| ML1 | 180 с | 190 с |
| ML2 | 90 с | 100 с |

Общий deadline job — 290 с по умолчанию (допустимый максимум backend 295 с).
Он включает upload, очередь и подготовку, поэтому полные лимиты обеих ML-стадий
не гарантируются одновременно; общий deadline может сработать раньше.
ML1 имеет собственный внешний предел 170 с. Ошибки остаются HTTP/job-ошибками.

- Нет Docker/WSL/Linux: остановиться и предоставить Linux runtime; не заменять
  нормализацию заглушкой и не отключать квоты.
- `ready=false`: проверить host.docker.internal, firewall и ML health; ключ
  требуется на analyze/jobs, не на health. `RULES_EMPTY` требует явного каталога.
- `PROCESSING_FAILED` на native Windows: backend использует Unix-only resource
  и SIGXFSZ; нужен Linux backend. Таймауты это не исправляют.
- Logs/health/report — только в `ml2/cache/jury/RUN/`. Не прикладывать JPEG,
  сырые ответы и закрытые видео к публичным отчётам.

Документация Docker: [доступ к сервисам хоста](https://docs.docker.com/desktop/features/networking/networking-how-tos/),
[Dockerfile-specific ignore](https://docs.docker.com/build/concepts/context/#filename-and-location).
