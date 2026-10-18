"""Group local evidence by original video; source annotations are never detections."""
import hashlib,json,math,re
from copy import deepcopy


def video_key(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value):
        raise ValueError('Original video SHA-256 required')
    return value


def event(video_sha,channel,kind,span,description,evidence=None,origin=None):
    video_key(video_sha)
    if len(span)!=2 or any(type(t) not in (int,float) or not math.isfinite(t) for t in span) or not 0<=span[0]<=span[1]:
        raise ValueError('Finite nonnegative event window required')
    fingerprint=json.dumps([video_sha,channel,kind,span,origin],sort_keys=True)
    return {'id':hashlib.sha256(fingerprint.encode()).hexdigest()[:20],
            'source_video_sha256':video_sha,'channel':channel,'type':kind,
            'start_sec':span[0],'end_sec':span[1],'description':description,
            'evidence':evidence or [],'origin':origin,'legal_violation_established':False}


def assemble(catalog,channels):
    """Join on video hash only, preserving separate evidence and annotation layers."""
    grouped={}
    for record in catalog['records']:
        digest=video_key(record['video_sha256'])
        case=grouped.setdefault(digest,{'source_video_sha256':digest,'source_names':[],
            'reference_annotations':[],'channels':[],'events':[],
            'analysis_status':'not_analyzed','analysis_complete':False,'verdict':None})
        if record['filename'] not in case['source_names']:case['source_names'].append(record['filename'])
        case['reference_annotations'].append(deepcopy(record))
    seen=set()
    for channel in channels:
        digest=video_key(channel['source_video_sha256'])
        if digest not in grouped:raise ValueError('Evidence video not in source catalog')
        if channel.get('legal_violation_established',False) is not False:raise ValueError('No automatic legal verdict')
        case=grouped[digest];summary={k:deepcopy(v) for k,v in channel.items() if k!='events'}
        case['channels'].append(summary);case['analysis_status']='partial'
        for item in channel.get('events',[]):
            if item['source_video_sha256']!=digest:raise ValueError('Cross-video event binding')
            if item.get('legal_violation_established') is not False:raise ValueError('No legal event verdict')
            if item['id'] not in seen:case['events'].append(deepcopy(item));seen.add(item['id'])
    cases=list(grouped.values())
    for case in cases:case['events'].sort(key=lambda e:(e['start_sec'],e['channel'],e['id']))
    return {'schema_version':'cashier-unified-local-review/1','analysis_complete':False,'verdict':None,
        'reference_annotations_used_as_predictions':False,'source_pdf_sha256':catalog['source_pdf_sha256'],
        'summary':{'unique_source_videos':len(cases),'videos_with_evidence':sum(bool(c['channels']) for c in cases),
            'videos_without_evidence':sum(not c['channels'] for c in cases),'source_rows':len(catalog['records']),
            'review_events':sum(len(c['events']) for c in cases),'legal_verdicts':0},'cases':cases}
