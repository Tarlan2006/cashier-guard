"""Local reference retrieval on other whole videos; no per-target seed or absence verdict."""
import base64, datetime, hashlib, html, json, sys, time
from pathlib import Path
import cv2
from run_ollama_trial import ROOT, write_json
from scene_mvp.document_search import SPEC, crop_box, templates, search, diverse_frames, iou


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_frames(record, folder, session):
    history = record['review_history'][-1]
    review = Path(history['path'])
    if sha(review) != history['accepted_file_sha256']:
        raise ValueError('Accepted human review changed')
    accepted = json.loads(review.read_text())
    protocol_path = review.parent/'protocol.local.json'
    if sha(protocol_path) != accepted['protocol_sha256']:
        raise ValueError('Human review protocol changed')
    reference = next(c for c in json.loads(protocol_path.read_text())['cases'] if c['sha256'] == record['source_video_sha256'])
    for frame in session['frames']:
        path = (folder/frame['file']).resolve()
        if not path.is_relative_to(folder.resolve()) or sha(path) != reference['frame_sha256'][frame['file']]:
            raise ValueError('Human-reviewed cached frame changed')


def main():
    cv2.setNumThreads(2)
    started = time.monotonic()
    pointer = json.loads((ROOT/'local/identity-dataset-current.local.json').read_text())
    dataset = Path(pointer['dataset'])
    labels = [json.loads(s) for s in (dataset/'video-observations.jsonl').read_text().splitlines()]
    reference = next(r for r in labels if r['source_session'] == 'scene-session-20261018-014424-318521')
    targets = [r for r in labels if r['source_video_sha256'] != reference['source_video_sha256']]
    source = ROOT/'local'/reference['source_session']
    session = json.loads((source/'session.local.json').read_text())
    if sha(Path(session['source_video'])) != reference['source_video_sha256']:
        raise ValueError('Reference source changed')
    validate_frames(reference, source, session)
    seed = reference['document_seed']
    anchor = min(session['frames'], key=lambda f: abs(f['timestamp_sec']-seed['timestamp_sec']))
    if abs(anchor['timestamp_sec']-seed['timestamp_sec']) > .001:
        raise ValueError('Reference seed must bind to a cached frame')
    ref_path = source/anchor['file']
    patch, _ = crop_box(cv2.imread(str(ref_path)), seed['bbox'])
    reference_templates = templates(patch)
    out = ROOT/'local'/('document-search-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir()
    protocol = {'schema_version': 'document-search-protocol/1', 'review_session': out.name, 'spec': SPEC,
                'reference_source_sha256': reference['source_video_sha256'], 'reference_seed': seed,
                'reference_frame_sha256': sha(ref_path), 'reference_native_pixels': list(patch.shape[1::-1]),
                'runner_sha256': sha(Path(__file__)), 'search_module_sha256': sha(ROOT/'scene_mvp/document_search.py'),
                'target_video_sha256': [r['source_video_sha256'] for r in targets],
                'target_object_boxes_or_times_used_by_search': False, 'targets_prior_human_labels_known': True,
                'independent_evaluation': False, 'no_match_does_not_establish_absence': True,
                'bank_data_uploaded': False, 'face_recognition_used': False, 'ocr_used': False,
                'approved_for_rule_engine': False, 'identity_verification_established': False}
    write_json(out/'protocol.local.json', protocol)
    timelines = []; evaluations = []; cards = []
    print('DOCUMENT_SEARCH:', out, flush=True)
    for target in targets:
        folder = ROOT/'local'/target['source_session']
        data = json.loads((folder/'session.local.json').read_text())
        if sha(Path(data['source_video'])) != target['source_video_sha256']:
            raise ValueError('Target source changed')
        validate_frames(target, folder, data)
        rows = []
        images = [cv2.imread(str(folder/f['file'])) for f in data['frames']]
        for index, frame in enumerate(data['frames']):
            frame_path = folder/frame['file']
            image = images[index]
            neighbors = [images[n] for n in (index-1,index+1) if 0 <= n < len(images)]
            proposals = search(image, reference_templates, neighbors=neighbors)
            rows.append({'timestamp_sec': frame['timestamp_sec'], 'file': frame['file'],
                         'frame_sha256': sha(frame_path), 'proposals': proposals})
        timelines.append({'source_session': target['source_session'], 'source_video_sha256': target['source_video_sha256'],
                          'source_name': data['source_name'], 'timeline': rows,
                          'document_presentation_status': 'not_established_by_retrieval'})
        # Target annotation is consulted only after all target predictions are computed.
        check = {'source_name': data['source_name'], 'frames_scanned': len(rows),
                 'human_video_observation': target['physical_document_observation'],
                 'max_similarity': max(p['reference_similarity'] for r in rows for p in r['proposals']),
                 'presentation_detected': None, 'document_absence_detected': False}
        if target.get('document_seed'):
            truth = target['document_seed']
            row = min(rows, key=lambda r: abs(r['timestamp_sec']-truth['timestamp_sec']))
            picked = diverse_frames(rows)
            check.update(seed_check_timestamp_sec=row['timestamp_sec'], seed_check_top3_iou=[iou(p['bbox'], truth['bbox']) for p in row['proposals']],
                         known_presentation_window_in_ranked_preview=any(target['presentation_window_sec'][0] <= r['timestamp_sec'] <= target['presentation_window_sec'][1]+.001 for r in picked),
                         seed_check_scope='one_preexisting_human_box_after_search_not_whole_video_detection_accuracy')
        evaluations.append(check)
        for row in diverse_frames(rows):
            image = cv2.imread(str(folder/row['file'])); h, w = image.shape[:2]
            for index, prop in enumerate(row['proposals']):
                a, b, c, d = [round(v) for v in [prop['bbox'][0]*w, prop['bbox'][1]*h, prop['bbox'][2]*w, prop['bbox'][3]*h]]
                color = [(50, 190, 50), (255, 170, 40), (180, 60, 220)][index]
                cv2.rectangle(image, (a,b), (c,d), color, 1)
                cv2.putText(image, chr(65+index), (a,max(12,b-3)), cv2.FONT_HERSHEY_SIMPLEX, .45, color, 1)
            # Only the fixed work-surface ROI is displayed; source pixels remain local.
            preview, _ = crop_box(image, [.10, .32, .72, .68])
            ok, encoded = cv2.imencode('.jpg', preview, [cv2.IMWRITE_JPEG_QUALITY, 95])
            if not ok: raise ValueError('Preview encode failed')
            key = str(len(cards))
            cards.append({'key': key, 'source_video_sha256': target['source_video_sha256'],
                          'source_session': target['source_session'], 'source_name': data['source_name'],
                          'timestamp_sec': row['timestamp_sec'], 'frame_sha256': row['frame_sha256'], 'proposals': row['proposals'],
                          'image': 'data:image/jpeg;base64,'+base64.b64encode(encoded).decode()})
        print('SCANNED:', data['source_name'], len(rows), flush=True)
    write_json(out/'predictions.local.json', {'videos': timelines})
    write_json(out/'development-check.local.json', {'video_checks': evaluations, 'accuracy_established': False})
    write_json(out/'candidate-manifest.local.json', {'cards': [{k:v for k,v in c.items() if k != 'image'} for c in cards]})
    metadata = {'schema_version': 'document-search-review/1', 'review_session': out.name,
                'protocol_sha256': sha(out/'protocol.local.json'), 'approved_for_rule_engine': False,
                'candidate_manifest_sha256': sha(out/'candidate-manifest.local.json')}
    payload = {**metadata, 'cards': cards}
    template = (ROOT/'scene_mvp/document_search_review.html').read_text()
    (out/'review.html').write_text(template.replace('__PAYLOAD__', json.dumps(payload,ensure_ascii=False).replace('<','\\u003c')), encoding='utf-8')
    summary = {'scanned_video_groups': len(targets), 'scanned_frames': sum(len(r['timeline']) for r in timelines),
               'reference_native_pixels': protocol['reference_native_pixels'], 'review_cards': len(cards),
               'elapsed_sec': round(time.monotonic()-started,2), 'automatic_document_recognition_established': False,
               'absence_detection_validated': False, 'approved_for_rule_engine': False}
    write_json(out/'summary.local.json', summary)
    write_json(ROOT/'local/document-search-current.local.json', {'trial': str(out), 'report': str(out/'review.html'), 'status': 'needs_candidate_review'})
    print('DOCUMENT_SEARCH_READY:', out/'review.html', flush=True)
    print(json.dumps({'summary': summary, 'checks': evaluations}), flush=True)


if __name__ == '__main__':
    main()
