"""Import human handover review and export weak event labels plus unlabelled features."""
import argparse,datetime,hashlib,json
from pathlib import Path
from run_ollama_trial import ROOT,write_json
from scene_mvp.reviewed_transfers import validate_direction_review,deduplicate_windows

def main():
    p=argparse.ArgumentParser();p.add_argument('--review',type=Path,required=True);p.add_argument('--trial',type=Path,required=True);args=p.parse_args();trial=args.trial.resolve()
    if not trial.is_relative_to((ROOT/'local').resolve()):p.error('Local motion trial required')
    raw=args.review.read_bytes();review=json.loads(raw);source=json.loads((trial/'motion-observations.local.json').read_text());entries=validate_direction_review(review,source,trial.name);events=deduplicate_windows(entries);sha=hashlib.sha256(raw).hexdigest()
    (trial/'human-direction-review.original.local.json').write_bytes(raw)
    accepted={**review,'accepted_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'review_sha256':sha,'accepted_event_labels':events,'whole_video_accuracy_established':False,'candidate_recall_evaluated':False,'approved_for_rule_engine':False}
    write_json(trial/'human-direction-review.accepted.local.json',accepted)
    out=ROOT/'local'/('transfer-labels-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
    (out/'events.jsonl').write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in events),encoding='utf-8')
    (out/'features.jsonl').write_text(''.join(json.dumps({'source_video_sha256':source['source_video_sha256'],'source_session':source['source_session'],**r},ensure_ascii=False)+'\n' for r in source['timeline']),encoding='utf-8')
    result={'event_windows':len(events),'raw_review_entries':len(entries),'duplicate_review_entries_merged':len(entries)-len(events),'confirmed_handovers':sum(e['handover_confirmed'] is True for e in events),'reviewed_no_transfer':sum(e['handover_confirmed'] is False for e in events),'unclear':sum(e['human_label']=='unclear' for e in events),'feature_frames':len(source['timeline']),'source_video_sha256':source['source_video_sha256'],'review_sha256':sha,'source_motion_trial':trial.name,'independent_evaluation':False,'labels_outside_reviewed_windows':'unknown_not_negative','training_dataset_sufficient':False,'automatic_violation_labels_created':False}
    write_json(out/'manifest.local.json',result)
    (out/'README.txt').write_text('Проверенные окна передачи денег и признаки сохранённых масок.\n\n'
        'events.jsonl: ответы человека по предложенным и вручную указанным интервалам; это слабая разметка окна, не точные покадровые границы. Точные дубли объединены с сохранением источников.\n'
        'features.jsonl: признаки всех кадров, без автоматически назначенных меток нарушения или меток «норма» вне просмотренных окон.\n'
        'split_group — SHA-256 исходного видео: все кадры и копии одного видео должны оставаться в одном разделе train/validation/test.\n'
        'Этот ролик использовался для настройки; результат не является независимой оценкой точности.\n'
        'Известные пропуски трекинга сохранены. Законность действий не размечена. Для обучения данных пока недостаточно.\n',encoding='utf-8')
    print('TRANSFER_LABELS_READY:',out);print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
