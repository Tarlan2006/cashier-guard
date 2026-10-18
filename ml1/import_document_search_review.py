"""Accept human checks of retrieval boxes, never infer whole-video document absence."""
import argparse, datetime, hashlib, json
from pathlib import Path
from run_ollama_trial import ROOT, write_json


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(review, trial):
    if review.get('schema_version') != 'document-search-review/1' or review.get('review_session') != trial.name:
        raise ValueError('Wrong review/session')
    if review.get('protocol_sha256') != sha(trial/'protocol.local.json') or review.get('candidate_manifest_sha256') != sha(trial/'candidate-manifest.local.json'):
        raise ValueError('Search protocol or candidates changed')
    if review.get('confirmed') is not True or review.get('approved_for_rule_engine') is not False or review.get('absence_detection_validated') is not False:
        raise ValueError('Confirmed limited-scope candidate review required')
    if review.get('review_scope') != 'human_review_of_automatically_ranked_sampled_frame_candidates':
        raise ValueError('Wrong review scope')
    expected = json.loads((trial/'candidate-manifest.local.json').read_text())['cards']
    rows = review.get('reviews', [])
    if len(rows) != len(expected): raise ValueError('All displayed candidates must be reviewed')
    observations = []
    for row, candidate in zip(rows, expected):
        if {k:v for k,v in row.items() if k != 'human_selection'} != candidate:
            raise ValueError('Candidate source/frame/geometry changed')
        choice = row.get('human_selection')
        if choice not in {'A','B','C','none','unclear'}: raise ValueError('Unknown human answer')
        index = ord(choice)-65 if choice in {'A','B','C'} else None
        if index is not None and index >= len(row['proposals']): raise ValueError('Selected box was not displayed')
        observations.append({'source_session': row['source_session'], 'source_video_sha256': row['source_video_sha256'],
            'frame_sha256': row['frame_sha256'], 'timestamp_sec': row['timestamp_sec'], 'human_selection': choice,
            'document_candidate_box': row['proposals'][index]['bbox'] if index is not None else None,
            'label_scope': 'selected_retrieval_box_only', 'human_type_claim': 'document_identity_not_automatically_verified',
            'none_means': 'none_of_displayed_boxes_not_whole_frame_or_video_absence', 'legal_violation_label': None})
    return observations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial', type=Path, required=True); parser.add_argument('--review', type=Path, required=True)
    args = parser.parse_args(); trial = args.trial.resolve()
    if not trial.is_relative_to((ROOT/'local').resolve()): parser.error('Local trial required')
    raw = args.review.read_bytes(); review = json.loads(raw)
    try: observations = validate(review, trial)
    except ValueError as error: parser.error(str(error))
    (trial/'human-candidate-review.original.local.json').write_bytes(raw)
    accepted = {**review, 'review_sha256': hashlib.sha256(raw).hexdigest(),
                'accepted_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'observations': observations,
                'identity_verification_established': False, 'legal_violation_label': None}
    write_json(trial/'human-candidate-review.accepted.local.json', accepted)
    summary = {'reviewed_frames': len(observations), 'frames_with_human_selected_document_box': sum(r['document_candidate_box'] is not None for r in observations),
               'frames_without_correct_displayed_box': sum(r['human_selection']=='none' for r in observations),
               'unclear_frames': sum(r['human_selection']=='unclear' for r in observations), 'absence_detection_validated': False}
    write_json(trial/'candidate-review-summary.local.json', summary)
    pointer = ROOT/'local/document-search-current.local.json'
    current = json.loads(pointer.read_text())
    if Path(current['trial']).resolve() == trial:
        write_json(pointer, {**current, 'status': 'human_candidate_review_recorded', 'review_summary': summary})
    print('DOCUMENT_CANDIDATES_REVIEWED:', trial); print(json.dumps(summary))


if __name__ == '__main__': main()
