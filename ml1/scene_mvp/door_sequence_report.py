"""Local numerical report; raw predictions and frozen classifier remain intact."""
import hashlib
import html
import json
from pathlib import Path
from scene_mvp import door_temporal
from scene_mvp.door_model import metrics


def temporal_plan():
    return {'spec': door_temporal.SPEC,
            'source_sha256': hashlib.sha256(Path(door_temporal.__file__).read_bytes()).hexdigest()}


def write_report(rows, destination, *, independent, source):
    destination=Path(destination)
    filtered=door_temporal.confirm(rows)
    annotated=[(raw, out) for raw,out in zip(rows,filtered) if raw['expected'] in ('closed','open')]
    truth=[raw['expected'] for raw,out in annotated]
    summary={'protocol':temporal_plan(), 'independent_new_video':independent,
             'retrained':False, 'source':source, 'approved_for_rule_engine':False,
             'raw':metrics(truth,[raw['predicted'] for raw,out in annotated]),
             'temporal':metrics(truth,[out['predicted'] for raw,out in annotated]),
             'episodes':door_temporal.episode_metrics(rows,filtered),
             'human_unclear_excluded':len(rows)-len(annotated)}
    (destination/'temporal-metrics.local.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    (destination/'temporal-predictions.local.json').write_text(json.dumps({'predictions':filtered},indent=2))
    names={'open':'Открыта','closed':'Закрыта','unknown':'Неясно'}
    reason={'confirmed_now':'Подтверждено сейчас','confirmed_continuation':'Продолжение',
            'raw_unknown':'Неясный ответ модели','awaiting_confirmation':'Ожидает подтверждения'}
    body=''.join('<tr><td>'+str(raw['timestamp_sec'])+'</td><td>'+names[raw['expected']]+'</td><td>'+names[raw['predicted']]+'</td><td>'+names[out['predicted']]+'</td><td>'+reason[out['reason']]+'</td></tr>' for raw,out in zip(rows,filtered))
    e=summary['episodes']
    event_rows=''.join('<tr><td>'+str(r['first_observed_sec'])+'–'+str(r['last_observed_sec'])+'</td><td>'+str(r['overlapping_prediction_runs'])+'</td><td>'+str(r['first_confirmation_delay_sec'])+'</td></tr>' for r in e['human_runs'])
    comparison=''.join('<tr><td>'+label+'</td><td>'+str(summary[key]['correct'])+'/'+str(summary[key]['frames'])+'</td><td>'+str(summary[key]['false_open_frames'])+'</td><td>'+str(summary[key]['missed_open_frames'])+'</td><td>'+str(summary[key]['unknown'])+'</td></tr>' for key,label in [('raw','Один кадр'),('temporal','Последовательность')])
    status='Новый ролик: параметры были зафиксированы до разметки.' if independent else 'Разбор разработки на уже просмотренном ролике. Это не новая независимая проверка.'
    text='<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><style>body{font:18px system-ui;max-width:1100px;margin:30px auto;padding:20px}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:9px}</style><h1>Дверь: проверка последовательности</h1><p>'+html.escape(status)+'</p><p>Два последовательных ответа с интервалом не менее 0,5 с. При смене состояния — «неясно» до подтверждения. Неясный ответ или разрыв более 0,75 с сбрасывает подтверждение. Будущие кадры не меняют прошлые ответы. Это технические пороги, не норматив банка.</p><p>Перекрытие человеком отдельно не распознаётся. «Неясно» не означает, что дверь закрыта. Проверяется состояние двери, правовое нарушение не устанавливается.</p><table><tr><th>Вариант</th><th>Совпадения</th><th>Ложное открытие</th><th>Открыта → закрыта</th><th>Неясно</th></tr>'+comparison+'</table><h2>Эпизоды открытия</h2><p>Человеческих эпизодов: '+str(e['human_open_runs'])+'; с пересечением предсказания: '+str(e['human_runs_with_any_overlap'])+'; фрагментов предсказания: '+str(e['predicted_open_runs'])+'; без пересечения: '+str(e['predicted_runs_without_overlap'])+'. Пересечение не доказывает точные границы. Неясные промежутки не заполняются.</p><table><tr><th>Размеченный интервал, с</th><th>Фрагментов обнаружения</th><th>Задержка первого подтверждения, с</th></tr>'+event_rows+'</table><h2>Хронология</h2><table><tr><th>Секунда</th><th>Человек</th><th>Один кадр</th><th>Последовательность</th><th>Основание</th></tr>'+body+'</table><p>Исходная модель не переобучена. Автоматическое подключение к правилам выключено.</p></html>'
    (destination/'temporal-report.html').write_text(text,encoding='utf-8')
    return summary
