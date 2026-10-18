# Запасной стенд на Windows

Проверено 18.10.2026 на Windows, CPU i5-1240P, 8 ГБ RAM. Команды выполняются
из корня cashier-guard в Windows PowerShell 5.1 или PowerShell 7. Нужен один
checkout на `main`; установку инструментов выполняют заранее, явно. WSL/Docker
для этого способа не требуются. Результаты: [windows_report.md](../ml2/eval/stack/windows_report.md).

## Подготовка

Нужны Python 3.12 для ML, Python 3.14 для backend, uv, Node.js **22.12+ в ветке
22.x или 24.x**, npm, FFmpeg и ffprobe с libx264 в PATH. Примеры установки
инструментов (выполните нужные команды самостоятельно, затем откройте новое окно):

```powershell
winget install --id Python.Python.3.12 -e
winget install --id astral-sh.uv -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id Gyan.FFmpeg -e
uv python install 3.14

uv --version
node --version
npm.cmd --version
ffmpeg -version
ffprobe -version
```

Если установленная через winget версия Node не входит в поддержанные ветки,
установите 22.12+ (22.x) или 24.x. При ручной распаковке FFmpeg добавьте его
`bin` в PATH текущего PowerShell: `$env:PATH = 'D:/tools/ffmpeg/bin;' + $env:PATH`.
Launcher не устанавливает отсутствующие системные инструменты: он останавливается
и показывает, что подготовить.

Подготовьте два отдельных окружения:

```powershell
py -3.12 -m venv ml2/.venv
& ./ml2/.venv/Scripts/python.exe -m pip install -r ml2/requirements.txt
Push-Location backend
uv venv --python 3.14
uv sync --frozen
Pop-Location
Push-Location frontend
npm.cmd ci
npm.cmd run build
Pop-Location
```

Нужны локальные веса RT-DETR и SigLIP. Один из вариантов:

```powershell
# Способ 1: скачать закреплённые исходные веса и экспортировать их локально.
& ./ml2/.venv/Scripts/python.exe ml2/scripts/download_models.py --download

# Способ 2: использовать готовый распакованный набор (без повторного скачивания).
$env:ML_MODELS_DIR = 'D:/ml2-weights'
& ./ml2/.venv/Scripts/python.exe ml2/scripts/download_models.py --source $env:ML_MODELS_DIR --verify-only
```

В наборе должны быть `rtdetr_r18vd/` и `siglip-base-patch16-224/`. Хеши проверяются
скриптом по manifest; depth-модель не нужна. Без `ML_MODELS_DIR` используется
`ml2/models/`. Относительный `ML_MODELS_DIR` launcher разрешает от корня checkout.
При скачивании/экспорте следуйте также [ml2/README.md](../ml2/README.md).

Сеть нужна на подготовке зависимостей/весов. На обработке видео модели работают
локально. Не добавляйте в Git веса, исходные видео, `.env` и содержимое `work/`.

## Одна команда для запуска

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/start-stack.ps1
```

`Bypass` действует только для этого процесса и не меняет системную execution
policy. Можно вызвать `./scripts/start-stack.ps1` напрямую, если политика разрешает.
При каждом запуске проверяются версии окружений, установленные ML-пакеты,
целостность весов и свободные порты; выполняется объявленный `uv sync --frozen`.
Если `frontend/dist/index.html` отсутствует, launcher явно сообщает и выполняет
`npm ci`, затем `npm run build`. Это этап подготовки с возможным доступом к реестру
пакетов. Для запуска без сети подготовьте окружения и сборку заранее.

Если `.env` отсутствует или `API_KEY` пуст, launcher создаёт случайный ключ,
сохраняет в `.env` и ограничивает ACL текущим пользователем. Существующие настройки
сохраняются; значение ключа не печатается. Если ACL нельзя установить, запуск
останавливается. Ключ из `.env` укажите в настройках открытого сайта локально;
не помещайте его в URL, отчёты, Git или сообщения. Внешний `API_KEY` не заменяет
сохранённый в `.env` ключ для этого launcher.

| Сервис | Адрес | Проверка |
|---|---|---|
| Backend и собранный сайт | http://127.0.0.1:8000 | `/api/v1/ready`: `ready=true`, `mode=live` |
| Анализ видео, ML1-контракт из ml2 | http://127.0.0.1:8001 | `/health`: `status=ok` |
| Явный matching | http://127.0.0.1:8002 | `/health`: `status=ok`, `semantic_matching=false` |

Все uvicorn запускаются с `--workers 1`, без reload. Backend получает
`PIPELINE_MODE=live`, `ML1_URL=http://127.0.0.1:8001`,
`ML2_URL=http://127.0.0.1:8002`, абсолютный `RULES_PATH`, указывающий на
`data/rules.json`. Для сервисов установлены `HF_HUB_OFFLINE=1`,
`TRANSFORMERS_OFFLINE=1`, отключена телеметрия Hugging Face.
Логи: `work/stack/*.out.log` и `*.err.log`; локальное хранилище backend:
`work/stack/storage/`. Эти каталоги исключены из Git.

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health
Invoke-RestMethod http://127.0.0.1:8002/health
Invoke-RestMethod http://127.0.0.1:8000/api/v1/ready
Start-Process http://127.0.0.1:8000
```

`ready` проверяет доступность зависимостей, включая TCP-порты ML; само по себе это
не подтверждение качества анализа. Для сквозной проверки загрузите открытое видео
на сайте либо отправьте multipart `file` в `POST /api/v1/analyze` с `X-API-Key`,
затем опрашивайте `GET /api/v1/jobs/{job_id}` с тем же заголовком до терминального
статуса. Корректный результат — `done`; ошибки должны отображаться явно.

**Правила детектора сейчас выключены. `events=[]` и итоговый `no_violation`
означают «наблюдений нет», а не доказанное отсутствие нарушений.** Каталог из
восьми правил не включает их автоматически в детектор. Matching сопоставляет
только явный `rule_id`, без семантического анализа и юридической проверки.

## Проверка и остановка

Проверить готовность и сразу остановить всё запущенное:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/start-stack.ps1 -Check
```

Обычный запуск держите в отдельном окне. Нажмите **Ctrl+C** в этом окне либо
выполните из второго окна в том же checkout:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/start-stack.ps1 -Stop
```

Windows Job Object ограничивает остановку собственными деревьями процессов,
включая Python-worker и FFmpeg. `-Stop` сигнализирует владельцу через отдельное
событие, проверяя PID и время старта. Чужие процессы на портах не завершаются:
занятый порт вызывает ошибку. `-Stop` не требует установленного uv/ML-окружения.
Одновременный второй launcher из того же checkout блокируется lock-файлом.
Не удаляйте `windows-state.json` при работающем launcher. Логи/хранилище после
остановки остаются в `work/stack/`; ключ остаётся в `.env` для следующего запуска.

## Туннель для жюри (только инструкция)

Установку и вход в выбранный инструмент выполняет владелец стенда. Launcher
ничего из этого не устанавливает. После локальной проверки в другом окне:

```powershell
# Уже установленный Cloudflare Tunnel:
cloudflared tunnel --url http://127.0.0.1:8000

# ИЛИ уже установленный и авторизованный ngrok:
ngrok http 8000
```

Откройте выданный HTTPS-адрес, укажите API-ключ в настройках сайта и повторите
загрузку. Наружу нужен только 8000; 8001/8002 остаются на loopback. Ключ не
передавайте параметром URL. Туннель передаёт HTTP-трафик через провайдера;
используйте только разрешённые для такого показа видео. Эти инструкции не означают,
что внешний туннель проверен в отчёте. Остановите его Ctrl+C после демонстрации.

## Не дать ноутбуку уснуть

Подключите питание. Сначала сохраните текущие параметры, затем отключите сон от
сети на время стенда (изменение настроек выполняется вручную):

```powershell
powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE
powercfg /change standby-timeout-ac 0
```

Не закрывайте крышку: её действие задаётся отдельно в параметрах питания Windows.
После стенда восстановите прежний таймаут. Например, если было 30 минут:
`powercfg /change standby-timeout-ac 30`. Launcher параметры питания не меняет.
