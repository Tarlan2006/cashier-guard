"""Prepare one native-video review of cash handover and cash-counter timing."""
import datetime,hashlib,json,os
from pathlib import Path
import cv2
from run_ollama_trial import ROOT,write_json
from run_document_reference_search import validate_frames
from scene_mvp.document_procedure import SPEC


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    dataset=Path(json.loads((ROOT/'local/identity-dataset-current.local.json').read_text())['dataset'])
    rows=[json.loads(s) for s in (dataset/'video-observations.jsonl').read_text().splitlines()]
    doc=next(r for r in rows if r['source_session']=='scene-session-20261018-014424-318521')
    folder=ROOT/'local'/doc['source_session'];session=json.loads((folder/'session.local.json').read_text());validate_frames(doc,folder,session)
    video=Path(session['source_video'])
    if sha(video)!=doc['source_video_sha256']:raise ValueError('Original video changed')
    cap=cv2.VideoCapture(str(video));fps=float(cap.get(cv2.CAP_PROP_FPS));duration=float(cap.get(cv2.CAP_PROP_FRAME_COUNT))/fps;cap.release()
    out=ROOT/'local'/('document-cash-order-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
    os.link(video,out/'source.mov')
    protocol={'schema_version':'document-cash-order-protocol/1','review_session':out.name,'source_session':doc['source_session'],
        'source_video_sha256':doc['source_video_sha256'],'source_name':doc['source_name'],'source_video':str(video),
        'duration_sec':duration,'document_presentation_window_sec':doc['presentation_window_sec'],
        'accepted_document_observation':doc,'sequence_spec':SPEC,'native_video_review_required':True,
        'time_boundaries_are_approximate':True,'automatic_legal_verdict':False,'approved_for_rule_engine':False}
    write_json(out/'protocol.local.json',protocol)
    payload={'review_session':out.name,'source_session':doc['source_session'],'source_video_sha256':doc['source_video_sha256'],
        'protocol_sha256':sha(out/'protocol.local.json'),'duration_sec':duration,'document_window':doc['presentation_window_sec'],'video_file':'source.mov'}
    (out/'review.html').write_text((ROOT/'scene_mvp/document_cash_order_review.html').read_text().replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c')))
    write_json(ROOT/'local/document-cash-order-current.local.json',{'trial':str(out),'report':str(out/'review.html'),'status':'needs_human_cash_and_counter_timing'})
    print('DOCUMENT_CASH_COUNTER_REVIEW_READY:',out/'review.html')


if __name__=='__main__':main()
