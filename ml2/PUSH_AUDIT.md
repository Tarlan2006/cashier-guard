# Аудит файлов к push — ml2-service

Проверяется добавляемое содержимое ветки относительно origin/main и два корневых файла. Push не выполнялся.
Ранее опубликованные материалы других участников в базовой истории не менялись и не входят в этот список.

## Проблемы и исправления

- В прежнем локальном отчёте обнаружены метки и таймкоды по отдельным видео. Полная копия сохранена только в игнорируемом локальном кэше. Из индекса прежний отчёт убран через git rm --cached; в Git возвращён сокращённый отчёт только с агрегатами.
- Из конфигурации удалены списки отдельных ошибок таймкода; сохранены TP/FP/FN/TN, средние ошибки и пустой whitelist.
- Генератор подробного отчёта направлен в игнорируемый кэш; генератор публичной конфигурации исключает списки отдельных ошибок.
- Добавлены исключения для кадров, контактных листов, локальных меток, таблиц, PDF, дополнительных видеоформатов и весов.
- Неопубликованный локальный коммит заменяется финальным: исходные метки не должны оставаться в достижимой истории новой ветки.
- Секреты, личные абсолютные пути, видео, изображения, веса, окружения и исходные данные организаторов в списке не обнаружены. Публикуются код, синтетические тесты, конфиги, хеши публичных моделей и агрегированные метрики.

## Поиск секретов и путей

Выполнен rg по api_key, token и шаблону личного Windows-пути; дополнительно проверены приватные ключи, известные префиксы облачных ключей и присвоенные строковые credentials.
Совпадения проверены: имена переменных окружения в README, создание случайного временного API-ключа только в памяти интеграционного теста, библиотека tokenizers и имена файлов токенизатора. Значений рабочих ключей и личных путей нет.
Сырые совпадения остаются в игнорируемом локальном аудите; секретные значения в этот отчёт не выводятся.

## Подтверждение README

- Проверка клиента 13/13 включает 8 положительных и 5 отрицательных случаев, а не 13 обнаруженных клиентов.
- Команда тестов — unittest; pytest не установлен как зависимость проекта.
- Загрузчику требуется --download либо --source; запуск без аргументов не поддерживается.
- Ресурсный предел RAM не подтверждён замерами. Legacy-модули сохранены; часть ещё вызывается как совместимость.

## Список файлов и размеры

| Файл | Байт |
|---|---:|
| .gitignore | 979 |
| README.md | 25441 |
| ml2/INTEGRATION.md | 12129 |
| ml2/PUSH_AUDIT.md | 8176 |
| ml2/PUSH_FILES.txt | 3195 |
| ml2/README.md | 9154 |
| ml2/backend/__init__.py | 0 |
| ml2/backend/pipeline/__init__.py | 0 |
| ml2/backend/pipeline/analysis_worker.py | 7356 |
| ml2/backend/pipeline/analyze.py | 4354 |
| ml2/backend/pipeline/budget.py | 1431 |
| ml2/backend/pipeline/perception/__init__.py | 522 |
| ml2/backend/pipeline/perception/anchors.py | 8325 |
| ml2/backend/pipeline/perception/anchors_v2.py | 15688 |
| ml2/backend/pipeline/perception/appearance.py | 1362 |
| ml2/backend/pipeline/perception/config.py | 4526 |
| ml2/backend/pipeline/perception/counter.py | 8205 |
| ml2/backend/pipeline/perception/detector.py | 6553 |
| ml2/backend/pipeline/perception/facts.schema.json | 5973 |
| ml2/backend/pipeline/perception/fixtures.py | 22278 |
| ml2/backend/pipeline/perception/prob_roles.py | 11601 |
| ml2/backend/pipeline/perception/proposals.py | 10863 |
| ml2/backend/pipeline/perception/refine.py | 4923 |
| ml2/backend/pipeline/perception/refine_v5.py | 3165 |
| ml2/backend/pipeline/perception/reflections.py | 14803 |
| ml2/backend/pipeline/perception/roles.py | 18320 |
| ml2/backend/pipeline/perception/roles_v2.py | 9604 |
| ml2/backend/pipeline/perception/run.py | 10108 |
| ml2/backend/pipeline/perception/scene_geometry.py | 1590 |
| ml2/backend/pipeline/perception/scene_tracks.py | 10043 |
| ml2/backend/pipeline/perception/scene_vocab.py | 1667 |
| ml2/backend/pipeline/perception/semantic_model.py | 1864 |
| ml2/backend/pipeline/perception/semantic_vocab.py | 2251 |
| ml2/backend/pipeline/perception/timestamps.py | 3532 |
| ml2/backend/pipeline/perception/torch_detector.py | 4882 |
| ml2/backend/pipeline/perception/tracking.py | 8384 |
| ml2/backend/pipeline/prompts/scene_anchors.txt | 1252 |
| ml2/backend/pipeline/prompts/zone_states.txt | 2754 |
| ml2/backend/pipeline/resident.py | 5895 |
| ml2/backend/pipeline/semantic_engine.py | 21232 |
| ml2/backend/pipeline/state_engine.py | 17226 |
| ml2/backend/pipeline/track_rules.py | 6483 |
| ml2/backend/pipeline/video.py | 10174 |
| ml2/backend/pipeline/zone_linear.py | 2181 |
| ml2/backend/schemas.py | 3259 |
| ml2/configs/model_manifest.json | 3281 |
| ml2/configs/perception.json | 1203 |
| ml2/configs/rule_validation.json | 2058 |
| ml2/cv_common.py | 2494 |
| ml2/docs/models.md | 10991 |
| ml2/eval/v6/report.md | 8329 |
| ml2/eval/v6_long_video.py | 2252 |
| ml2/eval/v6_report.py | 9706 |
| ml2/eval/v6_tracks.py | 4563 |
| ml2/eval/v6_zones.py | 9955 |
| ml2/requirements.txt | 560 |
| ml2/rules/catalog.yaml | 3867 |
| ml2/scripts/__init__.py | 0 |
| ml2/scripts/analyze_local.py | 1337 |
| ml2/scripts/debug_perception.py | 13427 |
| ml2/scripts/download_models.py | 7942 |
| ml2/scripts/export_local_prompts.py | 3211 |
| ml2/scripts/export_perception_onnx.py | 11783 |
| ml2/scripts/export_scene_text.py | 4021 |
| ml2/scripts/export_siglip_zeroshot.py | 11252 |
| ml2/scripts/integration_check.py | 8674 |
| ml2/scripts/ml2_stub.py | 1097 |
| ml2/scripts/prepare_transport_catalog.py | 2819 |
| ml2/service/__init__.py | 0 |
| ml2/service/app.py | 6050 |
| ml2/service/evidence.py | 3109 |
| ml2/tests/test_analyze.py | 7401 |
| ml2/tests/test_counter.py | 9292 |
| ml2/tests/test_debug_perception.py | 1182 |
| ml2/tests/test_detector_cpu.py | 2697 |
| ml2/tests/test_first_seen.py | 2149 |
| ml2/tests/test_fixtures.py | 10440 |
| ml2/tests/test_perception_geometry.py | 6296 |
| ml2/tests/test_prob_roles.py | 3742 |
| ml2/tests/test_proposals.py | 3391 |
| ml2/tests/test_refine.py | 11931 |
| ml2/tests/test_reflections.py | 6428 |
| ml2/tests/test_resident.py | 1961 |
| ml2/tests/test_runtime_budget.py | 1240 |
| ml2/tests/test_scene_anchors.py | 4151 |
| ml2/tests/test_scene_roles.py | 5585 |
| ml2/tests/test_scene_tracks.py | 5794 |
| ml2/tests/test_semantic_engine.py | 4873 |
| ml2/tests/test_service.py | 5079 |
| ml2/tests/test_state_engine.py | 4255 |
| ml2/tests/test_transport_catalog.py | 1453 |
| ml2/tests/test_v5_inputs.py | 5150 |
| ml2/tests/test_v6_rules.py | 1918 |
| ml2/tests/test_video.py | 8298 |
| ml2/tests/test_zone_linear.py | 1797 |

Всего: 95 файлов, 584187 байт.
