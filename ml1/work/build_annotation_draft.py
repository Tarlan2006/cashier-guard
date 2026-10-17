"""Prepare metadata-only annotation scaffolding; never open video or read frames."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / 'outputs/forte_dataset_manifest.json').read_text())
videos = {v['id']: v for v in manifest['videos']}
result = {
    'schema_version': 1,
    'purpose': 'annotation_draft_not_model_output',
    'created_on': '2026-10-17',
    'description': 'Черновик локальной разметки. Заполнены только метаданные и временные отметки. Описания и юридическая классификация вводятся и проверяются локально.',
    'source_manifest': 'forte_dataset_manifest.json',
    'source_rule_catalog': 'forte_rules_kz.json',
    'source_video_root': None,
    'policy': {
        'video_content_processed': False,
        'all_source_annotations_preserved': True,
        'split_unit': 'sha256',
        'counts_are_candidates_not_confirmed_violations': True,
        'api_verdicts': ['violation', 'no_violation'],
        'do_not_use_as_prediction_lookup': True
    },
    'videos': []
}
for group in manifest['content_groups']:
    source = videos[group['content_group']]
    times = list(group['annotated_timecodes_sec'])
    if group['content_group'] == 'X-13':
        times.append(50)
    events = []
    for index, time in enumerate(sorted(set(times)), 1):
        event = {
            'event_id': f'{group["content_group"]}-E{index:02d}',
            'timecode_sec': time,
            'supporting_timecodes_sec': [52] if group['content_group'] == 'X-38' else [],
            'timecode_provenance': 'user_addition' if group['content_group'] == 'X-13' and time == 50 else 'organizer_annotation',
            'grouping_note': '33 и 52 секунды относятся к одному эпизоду по уточнению пользователя.' if group['content_group'] == 'X-38' else None,
            'review_status': 'needs_review',
            'observation_local': None,
            'type_local': None,
            'rule_references': [],
            'conditions_checked': False,
            'exceptions_checked': False,
            'is_omission': None,
            'context_start_sec': None,
            'context_end_sec': None,
            'complete_operation_visible': None,
            'evidence_frames_local': [],
            'review_note_local': None
        }
        events.append(event)
    result['videos'].append({
        'content_group': group['content_group'],
        'sha256': group['sha256'],
        'files': group['files'],
        'relative_video_paths': [f'videos/{file}' for file in group['files']],
        'duration_sec': source['metadata']['duration_sec'],
        'source_annotations': group['annotations'],
        'split': None,
        'full_video_review_status': 'not_reviewed',
        'events': events
    })
assert len(result['videos']) == 40
assert sum(len(v['events']) for v in result['videos']) == 23
assert sum(len(v['source_annotations']) for v in result['videos']) == 42
assert sum(len(v['events']) == 0 for v in result['videos']) == 19
target = root / 'outputs/forte_annotations_draft.json'
with target.open('x', encoding='utf-8') as file:
    json.dump(result, file, ensure_ascii=False, indent=2)
print('Created metadata-only draft: 40 unique videos, 42 source annotations, 23 candidate events, 19 source-negative video groups.')
