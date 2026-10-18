"""One compact local review for cash, counter and safe in X-13/X-14."""
import base64,datetime,hashlib,json,os,shutil,sys
from pathlib import Path
import cv2
from run_ollama_trial import ROOT,write_json


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    sys.path.insert(0,str(ROOT.parent/'ml2'))
    from backend.pipeline.video import VideoReader
    catalog=json.loads((ROOT/'outputs/forte_scenarios_from_pdf.json').read_text())
    if sha(Path(catalog['source_pdf']))!=catalog['source_pdf_sha256']:raise ValueError('Source PDF changed')
    known=json.loads((ROOT/'local/scene-session-20261018-004941-345977/session.local.json').read_text())
    video_root=Path(known['source_video']).parent
    out=ROOT/'local'/('cash-process-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
    cases=[];protocol_cases=[]
    for name in ['X-13','X-14']:
        ref=next(r for r in catalog['records'] if r['video_id']==name);video=video_root/ref['filename']
        if sha(video)!=ref['video_sha256']:raise ValueError('Source video changed')
        source=out/name;source.mkdir();frames=[]
        with VideoReader(video) as reader:
            duration=reader.metadata.duration_sec
            for index,sample in enumerate(reader.iter_samples(.5)):
                ok,encoded=cv2.imencode('.jpg',sample.frame_bgr,[cv2.IMWRITE_JPEG_QUALITY,90])
                if not ok:raise ValueError('Frame encode failed')
                file=f'frame-{index:03d}.jpg';(source/file).write_bytes(encoded.tobytes());h,w=sample.frame_bgr.shape[:2]
                frames.append({'timestamp_sec':sample.actual_timestamp_sec,'file':file,'width':w,'height':h})
        local_video=out/(name+'.mov')
        try:os.link(video,local_video)
        except OSError:shutil.copy2(video,local_video)
        session={'session_id':source.name,'source_name':ref['filename'],'source_video_sha256':ref['video_sha256'],
            'source_video':str(video),'frames':frames,'duration_sec':duration,'person_detection_performed':False,'privacy':'local_only'}
        write_json(source/'session.local.json',session)
        record={'case_id':name,'source_session':str(source),'source_video_sha256':ref['video_sha256'],
            'duration_sec':duration,'sample_times_sec':[f['timestamp_sec'] for f in frames],
            'frame_sha256':{f['file']:sha(source/f['file']) for f in frames},'expected_outcome_not_prefilled':True}
        protocol_cases.append(record)
        cases.append({'case_id':name,'name':ref['filename'],'source_session':str(source),'source_video_sha256':ref['video_sha256'],
            'duration_sec':duration,'video_file':local_video.name,'frames':[dict(f,image='data:image/jpeg;base64,'+base64.b64encode((source/f['file']).read_bytes()).decode()) for f in frames]})
    protocol={'schema_version':'cash-process-plan/1','review_session':out.name,'cases':protocol_cases,
        'source_pdf_sha256':catalog['source_pdf_sha256'],'source_annotations_shown_as_model_answers':False,
        'frames_sampled_every_sec':.5,'all_native_frames_processed':False,'automatic_verdict':False}
    write_json(out/'protocol.local.json',protocol)
    payload={'review_session':out.name,'protocol_sha256':sha(out/'protocol.local.json'),'cases':cases}
    template=(ROOT/'scene_mvp/cash_process_review.html').read_text()
    (out/'review.html').write_text(template.replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c')),encoding='utf-8')
    write_json(ROOT/'local/cash-process-current.local.json',{'trial':str(out),'report':str(out/'review.html'),'status':'needs_three_regions_per_video'})
    print('CASH_PROCESS_REVIEW_READY:',out/'review.html',flush=True)
    print(json.dumps({'videos':len(cases),'frames':sum(len(c['frames']) for c in cases),'labels_prefilled':0}),flush=True)


if __name__=='__main__':main()
