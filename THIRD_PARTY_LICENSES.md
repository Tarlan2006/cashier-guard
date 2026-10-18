# Third-party licenses: стенд Cashier Guard

Проверено 2026-10-18 на базе main `8372756`. Охват: все прямые зависимости
ml2/requirements.txt, runtime/dev-зависимости backend/pyproject.toml с версиями
backend/uv.lock, runtime/dev-зависимости frontend/package.json с версиями
frontend/package-lock.json, модели ml2 и явно используемые FFmpeg/шрифты.
Полный реестр всех транзитивных npm/Python-компонентов этим документом не заявляется.

Для Python прочитаны importlib.metadata: Version, License-Expression, License,
Classifier, Project-URL и вложенные LICENSE. Это метаданные реально установленного
Windows wheel; лицензии встроенных библиотек могут отличаться между сборками.
Frontend node_modules отсутствует: лицензии сверены по lock-файлу и метаданным
точной версии в первичном npm registry, без установки/изменения frontend.

«С условиями» означает, что коммерческое использование допускается указанной
лицензией при выполнении её условий. Нужно сохранять применимые LICENSE/NOTICE,
copyright и disclaimers; для Apache — учитывать также NOTICE/изменения и патентные
условия, для bundled/copyleft-компонентов — их отдельные требования.
Этот реестр не заменяет тексты лицензий в распространяемых wheels/бинарниках.
«Не проверено» оставлено там, где нужная установленная версия отсутствует.

## Модели

Названия, revision и лицензии сверены с configs/model_manifest.json,
configs/depth_model_manifest.json и локальными карточками закреплённых моделей.
В каждой карточке license: apache-2.0. Веса и карточки с весами в Git не добавлялись.

| Модель | Версия / revision | Лицензия | Коммерческое использование | Источник проверки |
|---|---|---|---|---|
| PekingU/rtdetr_r18vd | ac77a11ff0170a41b771c03264987f8ce2b0d753 | Apache-2.0 | С условиями | [Pinned model card](https://huggingface.co/PekingU/rtdetr_r18vd/blob/ac77a11ff0170a41b771c03264987f8ce2b0d753/README.md), manifest и локальная карточка |
| google/siglip-base-patch16-224 | 7fd15f0689c79d79e38b1c2e2e2370a7bf2761ed | Apache-2.0 | С условиями | [Pinned model card](https://huggingface.co/google/siglip-base-patch16-224/blob/7fd15f0689c79d79e38b1c2e2e2370a7bf2761ed/README.md), manifest и локальная карточка |
| depth-anything/Depth-Anything-V2-Small-hf | 5426e4f0f36572d16453bbda7a8389317b1bef99 | Apache-2.0 | С условиями | [Pinned model card](https://huggingface.co/depth-anything/Depth-Anything-V2-Small-hf/blob/5426e4f0f36572d16453bbda7a8389317b1bef99/README.md), depth manifest; опциональный эксперимент, default выключен |

## ML2: все 18 прямых Python-зависимостей

Источник «METADATA» ниже — установленный distribution в ML-окружении; ссылки PyPI
идентифицируют точную версию. Для составных wheel перечисление SPDX сохранено из
License-Expression; дополнительные bundled-лицензии оговорены после таблицы.

| Пакет | Версия | Лицензия | Коммерческое использование | Источник проверки |
|---|---|---|---|---|
| torch | Требуется 2.14.1; установлен 2.14.1+cpu | Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND MIT | С условиями всех компонентов | METADATA License-Expression, dist-info/licenses/LICENSE; [PyPI](https://pypi.org/project/torch/2.14.1/) |
| numpy | 2.5.2 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0; bundled-лицензии отдельно | С условиями | METADATA License-Expression, licenses/LICENSE.txt; [PyPI](https://pypi.org/project/numpy/2.5.2/) |
| pillow | 12.3.0 | MIT-CMU | С условиями | METADATA License-Expression; [PyPI](https://pypi.org/project/pillow/12.3.0/) |
| opencv-python | 5.0.0.93 | MIT для wrapper; Apache-2.0 для OpenCV; bundled-лицензии отдельно | С условиями | METADATA заявляет Apache 2.0; cv2/LICENSE.txt и LICENSE-3RD-PARTY.txt уточняют компоненты; [PyPI](https://pypi.org/project/opencv-python/5.0.0.93/) |
| av | 19.0.1 | BSD-3-Clause; FFmpeg отдельно | С условиями | METADATA License-Expression; [PyPI](https://pypi.org/project/av/19.0.1/) |
| openpyxl | 3.1.5 | MIT | С условиями | METADATA License / Classifier; [PyPI](https://pypi.org/project/openpyxl/3.1.5/) |
| transformers | 5.20.1 | Apache-2.0 | С условиями | METADATA License; [PyPI](https://pypi.org/project/transformers/5.20.1/) |
| tokenizers | 0.23.3 | Apache-2.0 | С условиями | METADATA Classifier Apache; версия 2.0 дополнительно сверена с [LICENSE тега v0.23.3](https://raw.githubusercontent.com/huggingface/tokenizers/v0.23.3/LICENSE) |
| scikit-learn | 1.9.1 | BSD-3-Clause | С условиями | METADATA License-Expression; [PyPI](https://pypi.org/project/scikit-learn/1.9.1/) |
| scipy | 1.18.1 | BSD-3-Clause для проекта; bundled-лицензии отдельно | С условиями | METADATA License и dist-info/LICENSE.txt; [PyPI](https://pypi.org/project/scipy/1.18.1/) |
| onnx | 1.23.2 | Apache-2.0 | С условиями | METADATA License-Expression; [PyPI](https://pypi.org/project/onnx/1.23.2/) |
| onnxruntime | 1.31.0 | MIT | С условиями | METADATA License / Classifier; [PyPI](https://pypi.org/project/onnxruntime/1.31.0/) |
| pypdf | 6.12.2 | BSD-3-Clause | С условиями | METADATA License-Expression; [PyPI](https://pypi.org/project/pypdf/6.12.2/) |
| fastapi | 0.143.3 | MIT | С условиями | METADATA License-Expression; [PyPI](https://pypi.org/project/fastapi/0.143.3/) |
| uvicorn | 0.54.0 | BSD-3-Clause | С условиями | METADATA License-Expression; [PyPI](https://pypi.org/project/uvicorn/0.54.0/) |
| python-multipart | 0.0.32 | Apache-2.0 | С условиями | METADATA License-Expression; [PyPI](https://pypi.org/project/python-multipart/0.0.32/) |
| httpx | 0.28.1 | BSD-3-Clause | С условиями | METADATA License / Classifier; [PyPI](https://pypi.org/project/httpx/0.28.1/) |
| jsonschema | 4.26.0 | MIT | С условиями | METADATA License-Expression; [PyPI](https://pypi.org/project/jsonschema/4.26.0/) |

В Windows wheels NumPy/SciPy LICENSE дополнительно перечисляет OpenBLAS
(BSD-3-Clause), LAPACK и GCC runtime с GPL-3.0-or-later WITH GCC-exception-3.1.
Исключение нельзя опускать или выдавать этот runtime за обычную GPL без исключения.
OpenCV LICENSE-3RD-PARTY содержит LGPL-текст для bundled FFmpeg; лицензия wrapper
не заменяет его. Точная совместимость других сборок/платформ отдельно не проверялась.

## Backend: все прямые runtime и dev-зависимости

Версии в первом столбце версий — текущий uv.lock. Backend не переустанавливался:
локальное окружение отстаёт от lock-файла, это зафиксировано, а не исправлено.

| Пакет | Версия lock / установленная | Лицензия | Коммерческое использование | Источник проверки |
|---|---|---|---|---|
| fastapi | 0.143.3 / 0.143.3 | MIT | С условиями | Backend METADATA License-Expression; uv.lock |
| uvicorn | 0.54.0 / 0.54.0 | BSD-3-Clause | С условиями | Backend METADATA License-Expression; uv.lock |
| python-multipart | 0.0.32 / 0.0.32 | Apache-2.0 | С условиями | Backend METADATA License-Expression; uv.lock |
| httpx | 0.28.1 / 0.28.1 | BSD-3-Clause | С условиями | Backend METADATA License / Classifier; uv.lock |
| python-dotenv | 1.2.4 / 1.0.1 | Для lock 1.2.4 не проверено; установленная 1.0.1 — BSD-3-Clause | Для 1.2.4 не проверено | Backend METADATA относится к 1.0.1; не переносится автоматически на lock-версию |
| pillow | 12.3.0 / 12.3.0 | MIT-CMU | С условиями | Backend METADATA License-Expression; uv.lock |
| reportlab | 4.5.1 / отсутствует | Не проверено | Не проверено | Есть в pyproject/uv.lock, установленного METADATA нет |
| pypdf (dev) | 6.21.1 / отсутствует | Не проверено для этой версии | Не проверено | Есть в uv.lock; версия ML2 6.12.2 не подменяет эту проверку |
| pytest (dev) | 9.1.1 / 9.1.1 | MIT | С условиями | Backend METADATA License-Expression; uv.lock |

## Frontend: все прямые runtime и dev-зависимости

Для каждой строки license/version из package-lock.json совпали с метаданными
точной версии npm registry. Проверялись декларации пакетов; node_modules и
полный состав вложенных лицензий после сборки frontend не проверены.

| Пакет | Версия lock | Лицензия | Коммерческое использование | Первичный источник, сверенный с lock |
|---|---|---|---|---|
| @fontsource-variable/manrope | 5.3.0 | OFL-1.1 | С условиями OFL | [npm metadata](https://registry.npmjs.org/%40fontsource-variable%2Fmanrope/5.3.0) |
| lucide-react | 0.468.0 | ISC | С условиями | [npm metadata](https://registry.npmjs.org/lucide-react/0.468.0) |
| react | 19.3.1 | MIT | С условиями | [npm metadata](https://registry.npmjs.org/react/19.3.1) |
| react-dom | 19.3.1 | MIT | С условиями | [npm metadata](https://registry.npmjs.org/react-dom/19.3.1) |
| @playwright/test | 1.64.1 | Apache-2.0 | С условиями | [npm metadata](https://registry.npmjs.org/%40playwright%2Ftest/1.64.1) |
| @testing-library/react | 16.3.3 | MIT | С условиями | [npm metadata](https://registry.npmjs.org/%40testing-library%2Freact/16.3.3) |
| @testing-library/user-event | 14.6.8 | MIT | С условиями | [npm metadata](https://registry.npmjs.org/%40testing-library%2Fuser-event/14.6.8) |
| @types/node | 26.6.5 | MIT | С условиями | [npm metadata](https://registry.npmjs.org/%40types%2Fnode/26.6.5) |
| @types/react | 19.3.0 | MIT | С условиями | [npm metadata](https://registry.npmjs.org/%40types%2Freact/19.3.0) |
| @types/react-dom | 19.3.0 | MIT | С условиями | [npm metadata](https://registry.npmjs.org/%40types%2Freact-dom/19.3.0) |
| @vitejs/plugin-react | 5.2.0 | MIT | С условиями | [npm metadata](https://registry.npmjs.org/%40vitejs%2Fplugin-react/5.2.0) |
| jsdom | 29.1.1 | MIT | С условиями | [npm metadata](https://registry.npmjs.org/jsdom/29.1.1) |
| prettier | 3.9.10 | MIT | С условиями | [npm metadata](https://registry.npmjs.org/prettier/3.9.10) |
| typescript | 5.9.3 | Apache-2.0 | С условиями | [npm metadata](https://registry.npmjs.org/typescript/5.9.3) |
| vite | 7.3.7 | MIT | С условиями | [npm metadata](https://registry.npmjs.org/vite/7.3.7) |
| vitest | 5.0.5 | MIT | С условиями | [npm metadata](https://registry.npmjs.org/vitest/5.0.5) |

## FFmpeg и встроенные шрифты

| Компонент | Версия | Лицензия | Коммерческое использование | Источник проверки |
|---|---|---|---|---|
| FFmpeg-библиотеки внутри PyAV Windows wheel | libavcodec 63.1.102, libavutil 61.1.102 | LGPL-3.0-or-later | С условиями LGPL для соответствующей сборки/распространения | av.library_versions; фактический avcodec_license() возвращает LGPL version 3 or later |
| FFmpeg CLI для проверки видео | 9.0.2 essentials_build | GPL-3.0-or-later | С условиями GPL для соответствующего бинарника/распространения | Фактический ffmpeg -L; configure содержит --enable-gpl --enable-version3 |
| DejaVu Sans / Bold в backend | Версия файла не проверена | Bitstream Vera / Arev; изменения DejaVu public domain | С условиями лицензии шрифта | [Включённый LICENSE](backend/app/fonts/LICENSE.txt) |

Лицензия PyAV BSD не означает, что встроенный FFmpeg тоже BSD. На Mac нужно
проверить конкретный wheel/FFmpeg; Windows-результат на него не переносится.
Веса моделей остаются Apache-2.0; лицензии библиотек и кодеков учтены отдельно.

## Проверка публикуемого дерева Git

До добавления документов: 257 отслеживаемых файлов (git ls-files -z).
В текущем отслеживаемом дереве не найдено видео, JPEG/PNG-кадров, весов
(.onnx/.pt/.pth/.safetensors/.bin), файлов больше 5 000 000 байт или
личных абсолютных путей. Реальных токенов/приватных ключей не обнаружено.
Поиск включал PEM private-key headers, типовые provider-token patterns и
литеральные присваивания api_key/access_token/secret_key/password.

Единственное совпадение литерального API_KEY: ml2/eval/chain/RUNBOOK.md:141 —
shell command substitution с secrets.token_hex, команда генерации, не ключ.
Корневой .env.example отслеживается с пустым API_KEY; корневого .env нет.
Финальная проверка новых файлов выполняется перед push без вывода значений ключей.
Это поиск по текущим файлам, не полный аудит всей истории Git или всех секрет-форматов.

В ml1 уже отслеживаются материалы участника 2 (PDF/XLSX/JSON); они не входят
в наш ML1-сервис и не менялись. Draft [PR #4](https://github.com/Tarlan2006/cashier-guard/pull/4)
не интегрирован в этот аудит runtime. Исходные видео, веса и временные проверки
остаются вне публикуемого дерева; закрытые данные не использовались.
