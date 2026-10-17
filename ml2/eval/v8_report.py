"""Generate the v8 report from local numeric results, without source frames."""
import argparse
import json
from pathlib import Path
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from eval.distance_gate import promotion_gate
NAMES={'pixel':'Текущий центр / диагональ','foot':'Нижняя точка / диагональ','A':'A: гомография-прокси','B':'B: relative depth'}


def percent(value):return f'{value*100:.2f}%'


def stability(rows,key):
    return percent(statistics.mean(r['stability'][key] for r in rows)) if rows else 'недоступно'


def presence(row):
    summary=row['summary'];cashier=set(summary['cashier'])
    values=[]
    for identifier,track in summary['tracks'].items():
        prefix='К' if int(identifier) in cashier else 'Л' if int(identifier) in summary['clients'] else '?'
        uncertain='?' if track['uncertain'] else ''
        values.append(f"{prefix}{identifier}{uncertain}: {track['near_table_fraction']*100:.0f}/{track['near_machine_fraction']*100:.0f}")
    return '; '.join(values)


def generate(args):
    geometry=json.loads(args.geometry.read_text(encoding='utf-8'))
    rows=geometry['records']
    end=json.loads(args.end_to_end.read_text(encoding='utf-8'))
    methods=list(NAMES)
    baseline=[r for r in rows if r['method']=='pixel']
    gates={m:promotion_gate(baseline,[r for r in rows if r['method']==m]) for m in ('foot','A','B')}
    originals={(r['video'],r['method']):r for r in rows if r['variant']=='original' and r['status']=='ok'}
    videos=sorted({n for n,_ in originals})
    selected=sorted({(r['video'],r['variant']) for r in end if r['variant']!='original'})
    common=set(selected)
    for method in methods:
        common&={(r['video'],r['variant']) for r in end if r['method']==method and 'stability' in r}
    lines=['# v8 — расстояния на предполагаемой плоскости пола', '',
        'Дата: 2026-10-18. База кода: `5aa5ff3`, CPU i5-1240P, Python 3.12.10.',
        '**Решение: текущий расчёт оставлен по умолчанию. A и B не проходят критерий стабильности присутствия.**', '',
        '## Что сравнивалось', '',
        '- Восемь открытых видео: '+', '.join(map(str,videos))+'. Сначала переиспользованы одинаковые детекции/треки/якоря из открытого `production_inputs` v5: это контролируемый эксперимент по геометрии, а не новый прогон детектора.',
        '- Текущий метод: центр bbox, расстояния в долях диагонали кадра. Отдельная абляция: нижние середины bbox человека и опор без гомографии.',
        '- A: контуры светлой поверхности и границы в области стола, проверка покрытия всех desk-якорей; четыре вершины расширенной рабочей зоны, гомография в квадрат, нормировка на диагональ предполагаемой зоны. При отсутствии подходящего четырёхугольника — явно отмеченный affine fallback по desk bbox. Это **гипотеза плоскости**, а не измеренная калибровка пола.',
        '- B: Depth Anything V2 Small, один вызов на пиксельную временную медиану девяти равномерно выбранных кадров. Robust 2/98-percentile inverse-depth gauge, `z=1/(0.1+d_norm)`, условные лучи с фокусом, равным диагонали; расстояние между 3D-прокси, нормированное на рабочую зону. Ни фокус, ни эта gauge не считаются известными параметрами камеры. Расстояния **не в метрах**.',
        '- Нижняя середина bbox используется у людей и как приближение опорной точки предметов в A/B. У сидящих/закрытых столом людей это часто не стопы; машинка стоит на столе, а не на полу. Метрическая интерпретация не подтверждена ни на одном видео.',
        '- Пороги общие: near-table 0.08 диагонали, диагностический near-machine 0.12, масштаб anchor prior 0.30. Для A/B единицы автоматически пересчитываются через диаметр найденной зоны. Веса ролей, включая 5% anchor prior, не менялись; пороги не подбирались по номерам видео. Обучения нет.',
        '- Варианты: исходный, отражение, повороты +20° и −20° с расширенным холстом. Replay преобразует bbox в axis-aligned envelopes; нижняя точка такой рамки не равна преобразованной физической точке. Это 2D stress-test, не доказательство переноса на новый 3D-ракурс.', '',
        '## Роли на исходных видео', '',
        'ID — только локальные номера треков. Все методы сохранили те же роли; это не оценка их абсолютной точности.', '',
        '| Видео | Кандидат кассира: current / A / B | Клиенты: current / A / B | Изменение |',
        '|---|---|---|---|']
    for n in videos:
        cases=[originals[n,m]['summary'] for m in ('pixel','A','B')]
        c=['/'.join(map(str,r['cashier'])) or 'unknown' for r in cases]
        clients=[','.join(map(str,r['clients'])) or 'нет' for r in cases]
        lines.append(f"| {n} | {' / '.join(c)} | {' / '.join(clients)} | роли не изменились |")
    lines+=['', 'В 33 трек клиента помечен uncertain; это сохраняется, присутствие клиента не считается доказанным. В актуальном temporal-алгоритме роль в 18 уже определяется иначе, чем в старом proximity-heavy softmax: геометрия не исправила дополнительной ошибки роли.', '',
        '## Присутствие на исходных видео', '',
        'В ячейке: К = кандидат кассира, Л = кандидат клиента, ? = uncertain; ID: процент подтверждённых наблюдений **у стола / у машинки**. Это доли срабатывания признаков, **не accuracy** и не измеренные физические расстояния.', '',
        '| Видео | Текущий | A | B |', '|---|---|---|---|']
    for n in videos:lines.append(f"| {n} | {presence(originals[n,'pixel'])} | {presence(originals[n,'A'])} | {presence(originals[n,'B'])} |")
    fallback=sum('fallback' in str(originals[n,'A']['hypothesis_source']) for n in videos)
    lines+=['', f'A: {len(videos)-fallback}/{len(videos)} исходных сцен дали контурную гипотезу; {fallback}/{len(videos)} потребовали affine fallback. **Подтверждённых четырёх точек пола: 0/8.**', '',
        'Качественная проверка выполнена только по открытым кадрам с разрешения пользователя. На видимых рабочих позах у стола (например, середина 17) B может давать near-table=false; на видео 18 B повышает near-machine кассира, но это не даёт нового правильного назначения роли. В 4 нижняя точка/гомография значительно увеличивает near-machine клиента. В 33 B снимает near-machine с uncertain-трека, но без подтверждённых точек пола считать это улучшением точности нельзя. В 43 изменений нет. Для всех этих случаев нет разметки физических дистанций/стоп, поэтому оценка accuracy не выдумывается.', '',
        '## Стабильность при геометрическом replay', '',
        'Macro agreement по 8 видео × 3 преобразованиям = 24 случая; сравниваются те же ID и наблюдения с исходным вариантом каждого метода. Высокая согласованность сама по себе не означает правильный признак: near-table текущего метода часто всегда true из-за широкой desk bbox.', '',
        '| Метод | Роль | У стола | У машинки | Максимальная добавка, с | Включён |',
        '|---|---|---|---|---|---|']
    for method in methods:
        aug=[r for r in rows if r['method']==method and r['variant']!='original' and r['status']=='ok']
        extra=max(r['extra_sec'] for r in rows if r['method']==method and r['status']=='ok')
        lines.append(f"| {NAMES[method]} | {stability(aug,'role')} | {stability(aug,'near_table')} | {stability(aug,'near_machine')} | {extra:.3f} | {'да, прежний' if method=='pixel' else 'нет'} |")
    lines+=['', '| Метод / преобразование | Роль | У стола | У машинки |', '|---|---|---|---|']
    for method in methods:
        for variant in ('mirror','rotate_20','rotate_-20'):
            aug=[r for r in rows if r['method']==method and r['variant']==variant and r['status']=='ok']
            lines.append(f"| {method} / {variant} | {stability(aug,'role')} | {stability(aug,'near_table')} | {stability(aug,'near_machine')} |")
    error=max(r.get('footpoint_rotation_error_diag',0) for r in rows)
    lines+=['', f'Максимальная из медиан невязки bottom-midpoint при повороте: {error:.4f} диагонали кадра. Это артефакт axis-aligned bbox, а не измеренная ошибка физической стопы.', '',
        'Первый exploratory вариант допускал четырёхугольник, содержащий только один desk-якорь. Общая проверка геометрической валидности исправлена: должны входить все desk-якоря, добавлены замкнутые границы. До исправления A имел 90.46%/82.67% (стол/машинка), B — 84.76%/67.60%; итог о невключении не изменился. Числовые пороги близости не подбирались.', '',
        '## Полный конвейер с новыми детекциями', '',
        'Видео 18 и 33 перекодированы во все четыре варианта с одинаковым H.264/yuv420p CRF18, без звука. Исходные PTS сохранены у каждого кадра, FPS не используется как часы. Детектор, треки и якоря рассчитаны заново без кэша детекций. Производные видео остаются локально в cache/.', '',
        '| Видео | Вариант | Perception, с | A/B доступны | Покрытие bbox-сопоставлением |', '|---|---|---|---|---|']
    for n in sorted({r['video'] for r in end}):
        for variant in ('original','mirror','rotate_20','rotate_-20'):
            group=[r for r in end if r['video']==n and r['variant']==variant]
            baseline=next(r for r in group if r['method']=='pixel')
            available=all(any(r['method']==m and 'summary'in r for r in group) for m in ('A','B'))
            coverage=percent(baseline['stability']['coverage']) if 'stability'in baseline else 'контроль'
            lines.append(f"| {n} | {variant} | {baseline['perception_sec']:.2f} | {'да' if available else 'нет: потеря desk/якорей'} | {coverage} |")
    lines+=['', f'Есть {len(selected)} преобразованных случаев. A/B доступны только в {len(common)}/{len(selected)}; недоступные случаи не выкинуты из решения о включении. Сопоставление наблюдений — Hungarian IoU ≥0.2 при PTS-разнице ≤0.05 с, без лиц. Разные ID между прогонами не сравниваются напрямую.', '',
        f'Таблица ниже использует **одинаковые {len(common)} доступных случаев для всех методов**, чтобы потеря трудного случая не создавала ложного улучшения. Agreement считается только на сопоставленных bbox; пропущенные наблюдения отражены в покрытии.', '',
        '| Метод | Роль | У стола | У машинки | Покрытие | Max добавка, с |', '|---|---|---|---|---|---|']
    for method in methods:
        group=[r for r in end if r['method']==method and (r['video'],r['variant'])in common and 'stability'in r]
        extra=max(r['extra_sec'] for r in end if r['method']==method and 'extra_sec'in r)
        lines.append(f"| {NAMES[method]} | {stability(group,'role')} | {stability(group,'near_table')} | {stability(group,'near_machine')} | {stability(group,'coverage')} | {extra:.3f} |")
    lines+=['', 'Эта проверка выявила отдельную проблему восприятия: после +20° в 33 исчезают desk-якоря, даже у baseline теряется near-table. Новая геометрия не чинит отсутствие якорей. Все восемь perception-прогонов завершились полностью; шаг фактов 0.5 с.', '',
        '## Время, лицензия и решение', '',
        f'Добавка времени включает декодирование девяти кадров/медиану, автоматическую зону, depth inference только у B и повторный расчёт ролей/признаков; это консервативная верхняя оценка (не вычтены миллисекунды прежней геометрии). Загрузка depth-модели отдельно: {geometry["model_load_sec"]:.3f} с. Модель резидентная; при холодной загрузке на каждый запрос B превысит +5 с. В обычном сервисе она не загружается вообще.', '',
        'Depth Anything V2 **Small** (24.8M), `depth-anything/Depth-Anything-V2-Small-hf`, revision `5426e4f0f36572d16453bbda7a8389317b1bef99`, **Apache-2.0**. Лицензия проверена на [официальной странице HF-варианта](https://huggingface.co/depth-anything/Depth-Anything-V2-Small-hf) и [оригинального Small](https://huggingface.co/depth-anything/Depth-Anything-V2-Small). Base/Large не используются. Хеши/размеры: `configs/depth_model_manifest.json`; загрузка/копирование только явным `scripts/download_models.py --depth-small`. ML-инференс и расчёт метрик локальные, local_files_only, seed42; обучения нет, облачные AI API в конвейер не добавлены. Открытые QA-кадры показаны ассистенту по разрешению пользователя.', '',
        '**Gate:** роли должны быть не менее стабильны, присутствие не должно ухудшиться ни по столу, ни по машинке и должно улучшиться хотя бы по одному признаку; доступность не должна падать, warm добавка ≤5 с для каждого проверенного видео. A и B проходят время, но проваливают присутствие; B дополнительно меняет признаки даже при отражении. Нижняя точка без гомографии улучшает машинку, но ухудшает стол. Поэтому по умолчанию оставлен прежний расчёт. Пороги после просмотра результата не подгонялись.', '',
        'Слабые места: нет camera intrinsics, проверенных floor correspondences, реальных размеров зоны и разметки feet/near-state; не видны стопы сидящих людей; высоты anchors различаются; временная медиана сохраняет неподвижного кассира; относительная глубина и её нормализация не являются метрической реконструкцией; bbox-bottom не ковариантен вращению; ширина desk bbox и ошибки якорей ограничивают оба метода. Пока не получены такие данные, физическое улучшение расстояний заявлять нельзя.', '',
        '## Проверка и воспроизведение', '',
        '160 тестов пройдены в изолированном Python 3.12.10; проверены известная синтетическая гомография, вырожденные точки/глубина, сохранение baseline, лицензия/хеши optional bundle, PTS и ориентация настоящих H.264-аугментаций, gate стабильности/доступности/времени. Все существующие тесты сервиса проходят. Публичные файлы не содержат исходных видео, кадров, весов или абсолютных путей разработчика.', '',
        'Из ml2/, OPEN_ROOT — только открытый data/open, FACTS_DIR — локальные открытые production_inputs, MODEL_ROOT — проверенный RT-DETR/SigLIP комплект:', '',
        '```powershell', 'python scripts/download_models.py --depth-small',
        'python scripts/download_models.py --depth-small --verify-only',
        'python eval/v8_distances.py --open-root OPEN_ROOT --facts-dir FACTS_DIR --output cache/v8/final',
        'python eval/v8_end_to_end.py --open-root OPEN_ROOT --model-root MODEL_ROOT',
        'python eval/v8_report.py', 'python -m unittest discover -s tests', '```', '',
        'Числовые результаты и QA-листы находятся в игнорируемом cache/v8/. Просматривались только кадры открытого набора; закрытый набор не читался. Изменения ограничены ml2/; commits локальные, push не выполнялся.', '']
    lines += ['## Машинная проверка gate', '',
              '| Метод | Прошёл replay gate | Причины |', '|---|---|---|']
    for method,gate in gates.items():
        lines.append(f"| {method} | {gate['passed']} | {', '.join(gate['reasons']) or 'нет'} |")
    lines.append('')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text('\n'.join(lines),encoding='utf-8')
    return args.output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--geometry',type=Path,default=ROOT/'cache/v8/final/records.json')
    parser.add_argument('--end-to-end',type=Path,default=ROOT/'cache/v8/end_to_end/records.json')
    parser.add_argument('--output',type=Path,default=ROOT/'eval/v8/report.md')
    print(generate(parser.parse_args()))
