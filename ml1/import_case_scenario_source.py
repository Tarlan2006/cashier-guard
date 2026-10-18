"""Register the user's PDF as the scenario reference, separate from model answers/law."""
import argparse,collections,datetime,hashlib,json
from pathlib import Path
from import_pdf_annotations import extract
from run_ollama_trial import ROOT,write_json

def main():
    p=argparse.ArgumentParser();p.add_argument('--pdf',type=Path,required=True);args=p.parse_args()
    rows=extract(args.pdf,json.loads((ROOT/'outputs/forte_dataset_manifest.json').read_text()))
    digest=hashlib.sha256(args.pdf.read_bytes()).hexdigest();groups=collections.defaultdict(list)
    for r in rows:groups[r['video_sha256']].append(r['video_id'])
    records=[{**r,'source_order':i+1,'split_group':r['video_sha256'],'same_video_reference_ids':groups[r['video_sha256']]} for i,r in enumerate(rows)]
    catalog={'schema_version':'forte-pdf-scenarios/1','source_pdf':str(args.pdf.resolve()),'source_pdf_sha256':digest,
             'authority':'user_designated_primary_scenario_reference','registered_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'scope':['scenario_names','descriptions','reference_times','risk_labels','future_work_order'],
             'color_legend':{'red':'высокий риск для денег или доступа','yellow':'умеренный риск или нарушение порядка работы','green':'нарушение не выявлено'},
             'uncertainty_policy':'Слова «возможный» и «не видно» сохраняют неопределённость; цвет не является подтверждением нарушения.',
             'legal_sources_kept_separate':True,'previous_observations_preserved':True,'reference_labels_are_not_model_predictions':True,
             'expected_descriptions_not_used_as_answers_for_uploaded_video':True,'split_policy':'group_by_original_video_sha256',
             'records':records}
    target=ROOT/'outputs/forte_scenarios_from_pdf.json';write_json(target,catalog)
    selected=[r for r in records if r['risk_annotation']!='not_identified']
    worklist={'schema_version':'forte-pdf-worklist/1','source_pdf_sha256':digest,'source_catalog':'outputs/forte_scenarios_from_pdf.json',
              'active_reference_ids':['X-2'],'active_topic':'Предъявление и осмотр документа перед приёмом денег',
              'current_comparison_reference_ids':['X-3'],'related_separate_topic_reference_ids':['X-17'],
              'next_reference_id_after_active_in_pdf_order':'X-4','items':[{'source_order':r['source_order'],'reference_id':r['video_id'],
                 'source_page':r['source_page'],'timestamp_sec':r['reference_timestamp_sec'],'annotation_type':r['annotation_type'],
                 'risk_annotation':r['risk_annotation'],'split_group':r['split_group'],'status':'active' if r['video_id']=='X-2' else 'pending_scenario_check'} for r in selected],
              'prototype_components_are_not_proof_that_scenario_is_completed':True}
    write_json(ROOT/'outputs/forte_case_worklist.json',worklist)
    write_json(ROOT/'local/scenario-source-current.local.json',{'source_pdf':catalog['source_pdf'],'source_pdf_sha256':digest,'catalog':str(target),
               'worklist':str(ROOT/'outputs/forte_case_worklist.json'),'active_topic':'identity_document_presentation'})
    (ROOT/'SCENARIO_SOURCE.txt').write_text('Основной источник сценариев проекта: '+catalog['source_pdf']+'\nSHA-256: '+digest+'\n\n'
      'Названия, описания, временные отметки, цвета риска и порядок сценариев берём из этого PDF по прямому указанию пользователя.\n'
      'Машиночитаемый каталог: outputs/forte_scenarios_from_pdf.json. Очередь: outputs/forte_case_worklist.json.\n'
      'Сейчас: X-2 «Идентификация не видна», сравнение с X-3 (карточка перед банкнотами). X-17 — отдельная процедура передачи сумки.\n'
      'После текущего сценария следующий пункт по порядку PDF — X-4 «Неубранная наличность».\n'
      '«Возможный» и «не видно» сохраняем. Цвет — предварительный риск, а не доказанное нарушение.\n'
      'Прежние противоречащие трактовки не используем как целевые метки: X-1 — возврат части суммы с неизвестной причиной;\n'
      'X-11/X-22 — возможный ключ в замке; X-30/X-33 — возможный посторонний доступ; X-46 — напиток за столом.\n'
      'Правовые основания ведутся отдельно в outputs/forte_rules_kz.json; PDF не подменяет нормативный акт.\n'
      'Ожидаемые описания и номера файлов не используются как готовый ответ модели. Все копии одного SHA остаются в одной выборке.\n',encoding='utf-8')
    print('SCENARIO_SOURCE_REGISTERED:',target)
    print(json.dumps({'source_sha256':digest,'source_records':len(records),'unique_video_groups':len(groups),'risk_scenarios':len(selected),
                      'active':'X-2','comparison':'X-3','next':'X-4'},ensure_ascii=False))

if __name__=='__main__':main()
