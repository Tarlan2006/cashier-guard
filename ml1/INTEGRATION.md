# ML1: локальные эксперименты и передача в интеграцию

Дата: 18.10.2026. Эта инструкция описывает добавляемую ветку `ml1/`.
Подробный локальный HANDOFF с индивидуальными примерами передаётся команде отдельно.
Исходные видео, кадры, человеческие ответы, checkpoints, venv и история локальных
экспериментов не включены в этот коммит. Наличие исходников не означает, что новые
каналы уже подключены к HTTP-сервису.

## Что опубликовано

- CLI детекции/трекинга, калибровки, SAM-сопровождения, обучения небольших голов,
  импорта ручных ответов, проверки и сборки отчётов.
- `scene_mvp/`: геометрический и временной движки, работа с масками и
  последовательностями, шаблоны локальной разметки и синтетические тесты.
- Описания зависимостей, общий workflow хранения денег и serializer доказательств.

Базовые RT-DETR/SAM не дообучались. Локально обучались небольшие головы двери,
оставленного предмета, состояния шкафа и классификации уже найденных областей.
Надёжность всей автоматической денежной цепочки не установлена.

## Интерфейсы

Чистая функция геометрии:

```python
from scene_mvp.engine import analyze
result = analyze(frames, profile, video_sha256, door_observations=None)
```

`frames` — список кадров с фактическим временем в секундах и person tracks.
`profile` — подтверждённая калибровка schema_version=1 с SHA исходного видео,
`roles.cashier_ids/client_ids`, нормализованными зонами `[x1,y1,x2,y2]`.
ID относятся к одной сессии трекера, а не к постоянной личности человека.
Без калибровки: `needs_calibration`. При доступных наблюдениях: `partial`,
`signals`, `timeline`, `coverage`. Пропавший трек или маска остаются неизвестными.

Параметр `door_observations` принимает известные состояния только с источником
`human_frame_label`. Модельная дверь добавляется отдельно через
`experimental_door.infer` и `experimental_door.attach_review`.

```text
Видео → кадры каждые 0,5 с → RT-DETR → треки/отражения → роли и зоны
  → engine.analyze → кандидаты отхода/посетителей
  → optional frozen backbone + door head → экспериментальная дверь
  → optional human seed + SAM → маски → кандидаты оставленного предмета
  → export_scene_handoff.make_payload → JSON + 1–3 исходных JPEG
```

`export_scene_handoff.make_payload(result, session, source, duration)` возвращает
`(payload, event_metadata)`. Payload соответствует ML1 schema_version=1.0:
`events[].id/start_sec/end_sec/description/evidence_frames`.
Кадры: `timestamp_sec`, `image_base64` (JPEG без data-префикса).
Тип находится в sidecar metadata по event id. Текущий Observation-контракт не
содержит отдельных `type`, `rule_id`, `confidence` и полноты анализа.
Готового wrapper `analyze(video_path, facts=None)` для всех каналов пока нет.

## Команды и условия запуска

Команды из корня репозитория; веса и исходные локальные данные нужны отдельно:

```bash
python ml1/run_person_tracks_trial.py --video /path/to/video.mp4
python ml1/prepare_scene_mvp.py --video /path/to/video.mp4 --tracks /path/to/tracks
python ml1/run_scene_mvp.py --session /path/to/session --calibration /path/to/profile.json --experimental-door-model /path/to/door-model-directory
python ml1/run_sam2_object_trial.py --calibration /path/to/object-profile.json
python ml1/predict_object_event.py --model /path/to/object-event-model --observations /path/to/observations.local.json --calibration /path/to/calibration.local.json
python ml1/export_scene_handoff.py --scene-result /path/to/result
```

Калибровочные CLI пока сверяют исходный dataset manifest, session и video SHA.
Они не являются универсальным сервисом произвольного нового видео без адаптации.
Тип объекта, seed и роли в SAM-ветке задаёт человек; SAM не распознаёт банковский
смысл предмета по текстовому запросу. Общий обзор собирает готовые результаты,
а не выполняет повторный inference всех видео.

## Модели и assets

| Модель | Назначение | Лицензия / источник |
|---|---|---|
| RT-DETR R18, revision `ac77a11ff0170a41b771c03264987f8ce2b0d753` | ONNX CPU detector 384×384; frozen backbone голов | [Apache-2.0](https://huggingface.co/PekingU/rtdetr_r18vd/blob/ac77a11ff0170a41b771c03264987f8ce2b0d753/README.md) |
| SAM 2.1 Hiera Tiny, source `2b90b9f5ceec907a1c18123530e92e794ad901a4` | Human-seeded video segmentation | [Apache-2.0, включая checkpoints](https://github.com/facebookresearch/sam2#license) |
| Локальная door head | Logistic regression на frozen RT-DETR features | Собственные веса проекта, передаются отдельно |
| Локальная object event head | MIL logistic на трёх геометрических признаках | Собственные веса; поддерживаются `bag` и `documents`, деньги исключены |

RT-DETR: `model_384.onnx` 81 012 039 байт, `model.safetensors` 80 904 152 байта.
SAM checkpoint: 156 008 466 байт. Door head: 108 516 байт. Object event head:
1 223 байта. Нужны не только NPZ/PT, но и соответствующие metadata/config/LICENSE.

```text
RT-DETR ONNX SHA-256: d777f785af36550779f3227d358db8fac458e341de417312ee37543808609ffc
RT-DETR source SHA:   fe87a5a30f5daf298d10794c7682a63b6107986f97d6a770ba948d89e4340093
SAM checkpoint SHA:  7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69
Door head SHA:       785672274584466233ccc8f5bbe9158f4c5afa65969b9a85dd815f04fd795f5c
Object event SHA:    e99e4e8fa3b1f8f75b89ea7ded83b9b0cf31887147f4f2c9bc0a6079d7a41b76
```

SAM-скрипты читают локальный `local/runtime/sam2-runtime.local.json`: source_path,
weights_path и weights_sha256; файл и исходники SAM нужно подготовить на целевом
компьютере. В рабочем окружении SAM использовал MPS, CPU fallback не измерен.
Внешний накопитель хранит файлы и не увеличивает RAM.

VLM Qwen/SmolVLM, EdgeTAM и старый MLX-контур опубликованы как исходники опытов,
но не являются обязательными зависимостями срочного контура. Головы сейфа,
удостоверения и типа кропа не следует включать как подтверждённые правила.

## Зависимости и проверки

Проверенное локальное окружение: Python 3.12.14, macOS arm64. Версии основного
окружения — `requirements-perception-mac.txt`; SAM support —
`requirements-edgetam-local.txt`; старый MLX — `requirements-mac-local.txt`.
Не устанавливать одновременно `opencv-python` и `opencv-python-headless`.
Не переносить macOS arm64 wheels/venv на x86 Windows/Linux; нужны платформенные
сборки тех же совместимых версий.

```bash
PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s ml1/scene_mvp -t ml1 -p 'test_*.py' -q
```

Перед публикацией прошли 264 Python-теста (258 scene-модулей и 6 local-trial)
и 7 синтетических UI-проверок. Это проверки логики, а не качества на видео.
PyAV нужен обновлённому общему `ml2/backend/pipeline/video.py`; он не был установлен
в первоначальном perception-окружении ML1. В публикуемый requirements-perception-mac.txt
добавлен av==19.0.1; установленное рабочее окружение не изменялось. Зависимости общего сервиса
и его decoder проверять по `ml2/requirements.txt`.

## Метрики и производительность

- Дверь: 3 независимых новых видео, 132 кадра, 122 совпадения, 2 ложных open,
  4 open→closed, 4 unknown. Это состояния кадров, не точность событий нарушения.
- Object event head: 4 видео, development LOVO 4/4; исключение типа предмета 3/4.
  Один новый отрицательный контроль согласован с человеком. Временная MAE нет.
- Crop head: 6/11 верных первых гипотез; baseline «банкноты» 5/11. Надёжное
  распознавание денег/карты и физического удостоверения не установлено.
- Короткий person tracking: около 6–12 с на M2 CPU. SAM предмета на 30–46 samples:
  около 46–116 с дополнительно. Денежный SAM 417 samples: 737,71 с на M2 MPS.
- RAM peak не измерен. SAM eager loader имеет около 12 MiB/sample только под
  изображения; для 600 samples это примерно 7,03 GiB до модели и состояний.
- Полный ML1 анализ 5-минутного видео за 120 с на i5 CPU не подтверждён.

Не менять частоту без проверки: базовая сетка 0,5 с; object-event окна требуют
3 samples, span 0,8–1,3 с, gaps≤0,75 с. Пропуск кадров ломает окна и короткие действия.

## Состояние актуального общего сервиса

Публикация подготовлена поверх `origin/main` после `0bedcc9`. В этой версии
backend нормализует вход в MP4/H.264/yuv420p без аудио; нужно сохранять PTS и
начальный промежуток до первого видеокадра. Общий decoder использует PyAV.
Не применять к нему старое правило «номер кадра / FPS» или вычитание первого PTS.

Список `validated_rule_ids` общего сервиса остаётся пустым. Обновлённый сервис
возвращает успешный пустой Observation payload и `X-Rules-Enabled: none`.
Это не означает, что наши новые каналы подключены или что все нарушения проверены.
Новые `scene_mvp` results сохраняют собственную семантику partial/review/unknown;
перенос её в общий HTTP/report интерфейс требует явного решения интегратора.
Полный локальный HANDOFF фиксировал более ранний checkout и не заменяет чтение
текущих `ml2/README.md`, `ml2/INTEGRATION.md` и backend configs.

## Приоритет до сдачи

1. Принять свежий код и перенести нужные веса/metadata отдельно, не меняя текущие
   работающие процессы без готового интеграционного окружения.
2. Написать небольшой адаптер person facts + camera profile → scene candidates
   → ML1 JSON/JPEG; согласовать типы и partial/unknown со вторым этапом.
3. На конечной камере проверить роли и зоны, один положительный и один
   отрицательный пример, таймкоды/JPEG и предел времени.
4. Денежную цепочку оставить экспериментальной: дрейф маски, пропущенная машинка
   и неподтверждённое помещение нужной пачки в сейф ещё не исправлены.

Не запускать скачивание/обучение/HTML generation на обычном API-запросе.
Runtime использует местные веса без облачных AI API, анализа звука и распознавания
лиц. Download scripts обращаются к публичным источникам только при установке.
