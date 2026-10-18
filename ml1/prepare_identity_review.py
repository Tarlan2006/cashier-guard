"""Prepare local full-video evidence review; do not infer identity failure from absence."""
import base64,datetime,hashlib,json,os,shutil,sys
from pathlib import Path
from run_ollama_trial import ROOT,write_json

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def source_session(reference,video_root):
    for p in sorted((ROOT/'local').glob('scene-session-*/session.local.json')):
        s=json.loads(p.read_text())
        if s.get('source_video_sha256')==reference['video_sha256']:return p.parent,s
    # A document-evidence page needs raw frames, not person identities or inferred roles.
    sys.path.insert(0,str(ROOT.parent/'ml2'))
    from backend.pipeline.video import VideoReader
    import cv2
    video=video_root/reference['filename']
    if sha(video)!=reference['video_sha256']:raise ValueError('Reference video bytes changed')
    folder=ROOT/'local'/('scene-session-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));folder.mkdir();rows=[]
    with VideoReader(video) as reader:
        i=0
        while i*.5<reader.metadata.duration_sec:
            sample=reader.read_at(i*.5);ok,encoded=cv2.imencode('.jpg',sample.frame_bgr,[cv2.IMWRITE_JPEG_QUALITY,90])
            if not ok:raise ValueError('Document-review frame encode failed')
            name=f'frame-{i:03d}.jpg';(folder/name).write_bytes(encoded.tobytes());h,w=sample.frame_bgr.shape[:2]
            rows.append({'timestamp_sec':sample.actual_timestamp_sec,'file':name,'width':w,'height':h,'persons':[]});i+=1
    s={'schema_version':1,'session_id':folder.name,'source_name':video.name,'source_video_sha256':reference['video_sha256'],
       'source_video':str(video.resolve()),'tracks_folder':None,'frames':rows,'initial_roles':{},
       'source_type':'raw_video_sampling_no_person_inference','purpose':'identity_document_visual_review_only',
       'person_detection_performed':False,'automatic_person_absence_inference_allowed':False,'privacy':'local_only'}
    write_json(folder/'session.local.json',s)
    return folder,s

def main():
    out=ROOT/'local'/('identity-review-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
    previous_path=ROOT/'local/identity-current.local.json';previous=json.loads(previous_path.read_text()) if previous_path.exists() else None
    catalog_path=ROOT/'outputs/forte_scenarios_from_pdf.json';catalog=json.loads(catalog_path.read_text())
    if sha(Path(catalog['source_pdf']))!=catalog['source_pdf_sha256']:raise ValueError('Scenario PDF changed: register it again before review')
    lookup={r['video_id']:r for r in catalog['records']};definitions=[('X-3','cash_deposit'),('X-2','cash_deposit')]
    known=json.loads((ROOT/'local/scene-session-20261018-004941-345977/session.local.json').read_text());video_root=Path(known['source_video']).parent
    cases=[];manifest=[]
    for i,(reference_id,operation) in enumerate(definitions):
        reference=lookup[reference_id];folder,s=source_session(reference,video_root);session_id=s['session_id'];source=Path(s['source_video'])
        if sha(source)!=s['source_video_sha256']:raise ValueError('Video bytes changed')
        # Existing manual source labels are development context, not a blinded test.
        name=f'source-{i}.mov';dest=out/name
        try:os.link(source,dest)
        except OSError:shutil.copy2(source,dest)
        import cv2
        cap=cv2.VideoCapture(str(source));duration=round(float(cap.get(cv2.CAP_PROP_FRAME_COUNT)/cap.get(cv2.CAP_PROP_FPS)),3);cap.release()
        rows=[]
        for f in s['frames']:
            p=(folder/f['file']).resolve()
            if not p.is_relative_to(folder.resolve()):raise ValueError('Frame outside local session')
            rows.append({k:f[k] for k in ('timestamp_sec','width','height')}|{'image':'data:image/jpeg;base64,'+base64.b64encode(p.read_bytes()).decode()})
        cases.append({'session_id':session_id,'sha256':s['source_video_sha256'],'name':s['source_name'],'duration_sec':duration,'video_file':name,'frames':rows})
        manifest.append({'session_id':session_id,'sha256':s['source_video_sha256'],'name':s['source_name'],'duration_sec':duration,'operation_context':operation,
                         'video_file':name,'source_session_path':str(folder),'scenario_reference_id':reference_id,'source_pdf_page':reference['source_page'],
                         'frame_sha256':{f['file']:sha(folder/f['file']) for f in s['frames']}})
    protocol={'schema_version':'identity-observation-protocol/1','review_session':out.name,'cases':manifest,'legal_catalog_sha256':sha(ROOT/'outputs/forte_rules_kz.json'),
              'scenario_source_pdf_sha256':catalog['source_pdf_sha256'],'scenario_catalog_sha256':sha(catalog_path),
              'legal_basis_reference':'NBK-231 paragraphs 19(1),31(1); local legal copy revision 2026-03-16',
              'task':'visible_document_presentation_observations','physical_card_absence_does_not_establish_identity_failure':True,
              'digital_identity_status_requires_external_evidence':True,'native_video_playback_required_for_omission_review':True,
              'sam_object_type_requires_human_seed':True,'recognition_of_faces_or_reading_personal_document_data':False,
              'development_examples_prior_user_labels_known':True,'independent_evaluation':False,'automatic_legal_verdict':False}
    write_json(out/'protocol.local.json',protocol)
    payload={'review_session':out.name,'protocol_sha256':sha(out/'protocol.local.json'),'cases':cases,
             'previous_storage_key':'identity-review-'+Path(previous['review_folder']).name if previous else None}
    (out/'review.html').write_text((ROOT/'scene_mvp/identity_review.html').read_text().replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c')),encoding='utf-8')
    write_json(ROOT/'local/identity-current.local.json',{'review_folder':str(out),'report':str(out/'review.html'),'protocol_sha256':payload['protocol_sha256']})
    if previous:
        old=Path(previous['review_folder'])
        if old.is_relative_to(ROOT/'local'):
            write_json(old/'superseded.local.json',{'replacement':str(out),'reason':'Use PDF-defined X-3 comparison for X-2 rather than classifying X-1 partial cash return as a withdrawal','original_page_and_annotations_preserved':True})
    print('IDENTITY_REVIEW_READY:',out/'review.html');print(json.dumps({'videos':len(cases),'full_native_videos_available':True,'model_inference_used':False,'automatic_violation_labels_created':False}))

if __name__=='__main__':main()
