"""Assemble saved local analyses, apply the existing event head, and render one review."""
import base64,datetime,hashlib,html,json
from pathlib import Path
import numpy as np
from run_ollama_trial import ROOT,write_json
from scene_mvp.unified_review import assemble,event
from scene_mvp.object_event_model import extract,predict
from scene_mvp.cash_process import human_sequence

LOCAL=(ROOT/'local').resolve()
NAMES={'calibrated_scene':'Люди и дверь · сохранённые вычисления','seeded_object_tracking':'Предмет и уход · SAM с ручной подсказкой',
    'object_event_head':'Обученная модель оставленного предмета','human_cash_transfer':'Передача денег · твоя разметка',
    'human_cash_context':'Оставленная наличность · твоя разметка','human_procedure':'Документ, машина и сейф · твоя разметка',
    'human_cash_process':'Пересчёт и хранение выбранной порции · твоя разметка'}
KINDS={'workplace_departure':'Отход кассира','door_open_while_cashier_away':'Открытая дверь при отходе',
    'additional_visitor_near_service_zone':'Второй посетитель рядом','multiple_visitors_in_service_zone':'Несколько посетителей',
    'bag_observed_during_cashier_departure':'Сумка осталась при отходе','documents_observed_during_cashier_departure':'Документы остались при отходе',
    'cash_observed_during_cashier_departure':'Наличные остались при отходе','cash_handover':'Передача денег',
    'object_left_model_candidate':'Модель: окно оставленного предмета'}
STATES={'cash_handover_not_annotated':'Передача денег не размечена','not_a_confirmed_incoming_cash_handover':'Не является подтверждённым приёмом денег',
    'human_reported_document_transfer_precedes_cash':'По твоей проверке документ передан раньше денег',
    'visible_document_presentation_precedes_cash':'Предъявление документа наблюдается до денег',
    'physical_document_presentation_not_observed':'Предъявление физического документа не наблюдается',
    'document_clip_not_bound_to_one_client_cash_operation':'Документ виден, но не привязан к одной операции клиента',
    'counter_use_seen_after_combined_document_cash_window':'Машина использована после передачи документа и денег',
    'counter_use_seen_after_cash_handover_started':'Машина использована после начала передачи денег',
    'not_annotated':'Не размечено','incomplete_evidence':'Цепочка неполная: недостаточно наблюдений',
    'visual_procedure_review_candidate':'Есть основание проверить последовательность',
    'cash_stored_after_count_seen':'Помещение денег после пересчёта наблюдается',
    'storage_closed_after_placement_seen':'Последующее закрытие наблюдается',
    'same_client_operation_not_bound':'Не установлена связь с одной операцией',
    'cash_counter_use_seen':'Использование счётной машины наблюдается',
    'cash_counter_use_not_observed':'Использование машины не наблюдается',
    'placement_seen_count_order_not_established':'Помещение денег видно; пересчёт перед ним не установлен',
    'closure_seen_placement_order_not_established':'Закрытие видно; связь с помещением денег не установлена',
    'cash_storage_not_observed':'Помещение денег не наблюдается',
    'storage_closure_not_observed':'Закрытие сейфа не наблюдается',
    'count_storage_tail_supported_by_human_review':'Человек подтвердил пересчёт → помещение → закрытие для одной порции',
    'unknown':'Неясно'}


def read(path):return json.loads(path.read_text())
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def local_path(value):
    path=Path(value)
    if not path.is_absolute():path=LOCAL/path
    path=path.resolve()
    if not path.is_relative_to(LOCAL):raise ValueError('Expected local evidence path')
    return path


def session_for(value,sha):
    path=local_path(value);session=read(path/'session.local.json')
    if session['source_video_sha256']!=sha or session['session_id']!=path.name:raise ValueError('Source session/video mismatch')
    return path,session


def frames_for(source,session,times):
    result=[];frames=session['frames']
    for t in dict.fromkeys(times):
        f=next((f for f in frames if abs(f['timestamp_sec']-t)<.001),None)
        if not f:raise ValueError('Evidence timestamp not in source sampling')
        path=(source/f['file']).resolve()
        if not path.is_relative_to(source) or not path.is_file():raise ValueError('Evidence frame path')
        result.append({'timestamp_sec':f['timestamp_sec'],'file':str(path),'sha256':digest(path)})
    return result[:3]


def load_scene_channels():
    latest={};skipped=[]
    for pattern,channel_kind in [('scene-result-*','calibrated_scene'),('sam2-object-*','seeded_object_tracking')]:
        for folder in sorted(LOCAL.glob(pattern)):
            if not all((folder/f).exists() for f in ['status.json','observations.local.json','calibration.local.json']):continue
            status=read(folder/'status.json');profile=read(folder/'calibration.local.json');observations=read(folder/'observations.local.json')
            if status.get('status')!='completed' or observations.get('status')!='partial' or profile.get('confirmed') is not True:
                skipped.append({'folder':folder.name,'reason':'not_completed_confirmed_partial_result'});continue
            sha=profile['source_video_sha256'];source,session=session_for(profile['source_session'],sha)
            key=(sha,channel_kind,profile.get('target_object_kind') if channel_kind=='seeded_object_tracking' else None)
            events=[]
            for signal in observations['signals']+observations.get('experimental_signals',[]):
                if signal.get('legal_violation_established') is not False:raise ValueError('Expected review candidate')
                span=[signal['start_sec'],signal['end_sec']]
                events.append(event(sha,channel_kind,signal['type'],span,signal['explanation'],
                    frames_for(source,session,signal['evidence_times_sec']),origin=str(folder/'observations.local.json')))
            latest[key]={'source_video_sha256':sha,'kind':channel_kind,'source_session':session['session_id'],
                'result_file':str(folder/'observations.local.json'),'result_sha256':digest(folder/'observations.local.json'),
                'calibration_sha256':digest(folder/'calibration.local.json'),'report_file':str(folder/'report.html'),
                'target_kind':profile.get('target_object_kind'),'coverage':observations['coverage'],
                'human_roles_and_geometry_required':True,'type_recognition_automatic':False,
                'door_model_provenance':observations.get('experimental_door_provenance'),'events':events}
    return list(latest.values()),skipped


def object_heads(channels):
    directory=ROOT/'models/object_event_baseline';meta=read(directory/'model-metadata.local.json');weights=directory/'object-event-model.npz'
    if digest(weights)!=meta['model_sha256']:raise ValueError('Event model checksum mismatch')
    with np.load(weights,allow_pickle=False) as saved:model={k:saved[k] for k in saved.files}
    results=[]
    for channel in channels:
        if channel['kind']!='seeded_object_tracking' or channel['target_kind'] not in meta['supported_object_kinds']:continue
        folder=Path(channel['result_file']).parent;profile=read(folder/'calibration.local.json')
        features=extract(read(folder/'observations.local.json'),profile,meta['feature_spec']);answer=predict(model,features,meta['feature_spec'])
        sha=channel['source_video_sha256'];source,session=session_for(profile['source_session'],sha);events=[]
        candidate=answer.get('candidate')
        if candidate:
            events.append(event(sha,'object_event_head','object_left_model_candidate',[candidate['start_sec'],candidate['end_sec']],
                'Обученная модель выделила окно оставленного предмета. Границы предложены моделью; требуется проверка.',
                frames_for(source,session,candidate['evidence_times_sec']),origin=str(folder/'observations.local.json')))
        results.append({'source_video_sha256':sha,'kind':'object_event_head','target_kind':profile['target_object_kind'],
            'source_session':session['session_id'],'model_sha256':meta['model_sha256'],
            'is_training_video':sha in meta['source_video_sha256'],'evaluation_scope':'integration_not_new_accuracy_measurement',
            'input_observations_sha256':channel['result_sha256'],'joint_observed_coverage':features['joint_observed_coverage'],
            'prediction':answer['prediction'],'video_risk_score':answer['video_risk_score'],
            'score_is_calibrated_probability':False,'approved_for_rule_engine':False,'events':events})
    return results


def human_channels(procedure):
    result=[];seen=set()
    for folder in sorted(LOCAL.glob('transfer-labels-*')):
        path=folder/'events.jsonl'
        if not path.exists():continue
        for line in path.read_text().splitlines():
            label=json.loads(line);key=(label['source_video_sha256'],label['human_label'],tuple(label['reviewed_window_sec']))
            if key in seen or label.get('handover_confirmed') is not True:continue
            if label.get('legal_violation_label') is not None:raise ValueError('Expected human observation without legal label')
            seen.add(key);sha=label['source_video_sha256'];source,session=session_for(label['source_session'],sha)
            a,b=label['reviewed_window_sec'];frames=[f for f in session['frames'] if a-.001<=f['timestamp_sec']<=b+.001]
            times=[frames[0]['timestamp_sec'],frames[len(frames)//2]['timestamp_sec'],frames[-1]['timestamp_sec']] if frames else []
            direction={'client_to_cashier':'клиент → кассир','cashier_to_client':'кассир → клиент'}[label['human_label']]
            item=event(sha,'human_cash_transfer','cash_handover',[a,b],'Подтверждено человеком: '+direction+'. Границы приблизительные.',frames_for(source,session,times),str(path))
            result.append({'source_video_sha256':sha,'kind':'human_cash_transfer','source_session':session['session_id'],
                'human_label':label['human_label'],'boundaries_exact':False,'uncertain_tracking_times_sec':label.get('uncertain_tracking_times_sec',[]),
                'automatic_transfer_success_established':False,'result_file':str(path),'result_sha256':digest(path),'events':[item]})
    for case in procedure['cases']:
        result.append({'source_video_sha256':case['result']['source_video_sha256'],'kind':'human_procedure',
            'procedure':{k:v for k,v in case.items() if not k.startswith('source_pdf') and not k.startswith('scenario_reference')},
            'result_file':str(ROOT/'outputs/forte_document_cash_counter_sequence.json'),
            'result_sha256':digest(ROOT/'outputs/forte_document_cash_counter_sequence.json'),'events':[]})
    money=sorted(LOCAL.glob('money-dataset-*/cash-left-events.jsonl'))
    if money:
        for line in money[-1].read_text().splitlines():
            label=json.loads(line)
            result.append({'source_video_sha256':label['source_video_sha256'],'kind':'human_cash_context',
                'human_label':label['human_label'],'review_scope':label['review_scope'],
                'result_file':str(money[-1]),'result_sha256':digest(money[-1]),'events':[]})
    cash_process={}
    for path in sorted(LOCAL.glob('cash-process-*/human-review.accepted.local.json')):
        reviewed=read(path)
        if reviewed.get('confirmed') is not True:continue
        for case in reviewed['cases']:
            cash_process[(case['source_video_sha256'],case['cash_anchor_sec'])]={'source_video_sha256':case['source_video_sha256'],
                'kind':'human_cash_process','cash_seed_time_sec':case['cash_anchor_sec'],'result':human_sequence(case),
                'result_file':str(path),'result_sha256':digest(path),'events':[]}
    result.extend(cash_process.values())
    return result


def render(data):
    esc=html.escape;links=[];cards=[]
    for case in data['cases']:
        sha=case['source_video_sha256'];title=' / '.join(case['source_names']);has=bool(case['channels'])
        title_link='<a href="#v-'+sha[:12]+'">'+esc(title)+'</a>' if has else esc(title)
        links.append('<tr><td>'+title_link+'</td><td>'+('Есть частичные результаты' if has else 'Пока нет анализа')+'</td><td>'+str(len(case['events']))+'</td></tr>')
        if not has:continue
        body='<section id="v-'+sha[:12]+'"><h2>'+esc(title)+'</h2><p>Частичный анализ. Итог по нарушениям не установлен.</p>'
        for channel in case['channels']:
            body+='<article><h3>'+esc(NAMES[channel['kind']])+'</h3>'
            if channel['kind']=='human_procedure':
                states=channel['procedure']['result']
                labels={'document_state':'Документ','counter_state':'Счётная машина','storage_state':'Помещение денег в сейф','storage_closure_state':'Закрытие сейфа','visible_sequence_state':'Вся цепочка'}
                body+='<dl>'+''.join('<dt>'+label+'</dt><dd>'+esc(STATES.get(states.get(k),str(states.get(k,'Неясно'))))+'</dd>' for k,label in labels.items())+'</dl>'
            elif channel['kind']=='human_cash_process':
                states=channel['result'];labels={'counter_state':'Машина','storage_state':'Помещение денег','storage_closure_state':'Закрытие','visible_sequence_state':'Пересчёт и хранение'}
                body+='<dl>'+''.join('<dt>'+label+'</dt><dd>'+esc(STATES.get(states.get(k),str(states.get(k,'Неясно'))))+'</dd>' for k,label in labels.items())+'</dl><p>Только выбранная порция. Полная процедура приёма сумки и проверка передающего здесь не установлены.</p>'
            elif channel['kind']=='object_event_head':
                answer={'object_left_pattern':'Кандидат: предмет оставлен','no_object_left_pattern_detected':'Модель не выделила оставление предмета',None:'Недостаточно наблюдений'}[channel['prediction']]
                body+='<p>'+answer+'</p><p>'+('Это обучающий ролик модели, проверяется только подключение.' if channel['is_training_video'] else 'Ролик не входит в обучение этой модели; этот запуск не измеряет точность.')+'</p>'
            elif channel['kind'].startswith('human_'):
                labels={'client_to_cashier':'Клиент → кассир','cashier_to_client':'Кассир → клиент','cash_left_during_departure':'По твоей разметке деньги остались при уходе','cash_removed_before_departure':'По твоей разметке деньги убраны до ухода'}
                body+='<p>'+esc(labels.get(channel.get('human_label'),str(channel.get('human_label',''))))+'</p>'
            else:body+='<p>Роль кассира и зоны подтверждены для конкретного видео. Сохранённые результаты; повторная детекция не запускалась.</p>'
            body+='</article>'
        for item in case['events']:
            body+='<article><h3>'+esc(KINDS.get(item['type'],item['type']))+' · '+f"{item['start_sec']:.3f}–{item['end_sec']:.3f} с"+'</h3><p>'+esc(item['description'])+'</p><p>Источник: '+esc(NAMES[item['channel']])+'</p><div class="frames">'
            for f in item['evidence']:
                raw=Path(f['file']).read_bytes()
                if hashlib.sha256(raw).hexdigest()!=f['sha256']:raise ValueError('Evidence changed while rendering')
                body+='<figure><img loading="lazy" src="data:image/jpeg;base64,'+base64.b64encode(raw).decode()+'"><figcaption>'+f"{f['timestamp_sec']:.3f} с"+'</figcaption></figure>'
            body+='</div></article>'
        body+='<details><summary>Отдельно: исходная разметка PDF</summary>'+''.join('<p>'+esc(r['video_id'])+' · '+str(r['reference_timestamp_sec'])+' с · '+esc(r['annotation_type'])+'</p>' for r in case['reference_annotations'])+'<p>Эти подписи не использовались как ответы моделей.</p></details></section>'
        cards.append(body)
    summary=data['summary']
    return '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'"><title>Cashier Guard · общий ML-разбор</title><style>body{font:18px system-ui;max-width:1200px;margin:30px auto;padding:18px;line-height:1.5}aside{padding:18px;background:#fff1ce}section{margin:40px 0;padding:18px;border:1px solid #bbc8d3;border-radius:12px}article{margin:18px 0;padding:15px;background:#edf2f8}.frames{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}figure{margin:0}img{width:100%;max-height:550px;object-fit:contain}td,th{border-bottom:1px solid #ddd;text-align:left;padding:9px}table{border-collapse:collapse;width:100%}dt{font-weight:650}dd{margin-bottom:10px}a{color:#155ca4}</style><h1>Общий разбор ML</h1><aside>'''+'Частичные результаты собраны для '+str(summary['videos_with_evidence'])+' из '+str(summary['unique_source_videos'])+' уникальных видео. Событий для просмотра: '+str(summary['review_events'])+'. Это сборка выполненных анализов, не новый прогон всех видео. Пустой результат не означает норму.</aside><p>Цепочка принятых денег: документ → передача → счётная машина → помещение денег в сейф → закрытие. Неотмеченные этапы остаются неизвестными. Автоматическая проверка удостоверения личности, блокировки экрана, напитков и подлинности купюр пока не реализована.</p><p>Классификатор «банкноты / карта / другое» дал 6/11 верных первых гипотез и к правилам не подключён. SAM сопровождает цель, указанную человеком. Источники моделей и человеческой проверки разделены.</p><table><tr><th>Видео</th><th>Наличие результатов</th><th>События</th></tr>'+''.join(links)+'</table>'+''.join(cards)+'</html>'


def main():
    from build_document_procedure import build_and_save
    build_and_save()
    catalog=read(ROOT/'outputs/forte_scenarios_from_pdf.json')
    if digest(Path(catalog['source_pdf']))!=catalog['source_pdf_sha256']:raise ValueError('Source PDF changed')
    channels,skipped=load_scene_channels();channels+=object_heads(channels)
    channels+=human_channels(read(ROOT/'outputs/forte_document_cash_counter_sequence.json'))
    result=assemble(catalog,channels)
    result['skipped_incomplete_results']=skipped;result['models_retrained']=False
    result['full_video_inference_run_here']=False;result['cloud_data_transfer_used']=False
    result['object_crop_classifier_enabled']=False
    out=LOCAL/('unified-review-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
    write_json(out/'review.local.json',result);(out/'report.html').write_text(render(result),encoding='utf-8')
    write_json(LOCAL/'unified-review-current.local.json',{'trial':str(out),'report':str(out/'report.html'),
        'review':str(out/'review.local.json'),'summary':result['summary'],'analysis_complete':False,'verdict':None})
    print('UNIFIED_REVIEW_READY:',out/'report.html',flush=True);print(json.dumps(result['summary']),flush=True)


if __name__=='__main__':main()
