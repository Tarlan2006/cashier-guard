"""Extract independent hand proximity context from already reviewed local SAM masks."""
import argparse,datetime,hashlib,json
from pathlib import Path
from run_ollama_trial import ROOT,write_json
from scene_mvp.money_pipeline import check_mask_review,sha
from scene_mvp.money_contacts import PROTOCOL,candidates
from build_money_review import build

def main():
    import cv2,numpy as np
    p=argparse.ArgumentParser();p.add_argument('--trial',type=Path,required=True);args=p.parse_args();trial=args.trial.resolve()
    if not trial.is_relative_to((ROOT/'local').resolve()):p.error('Local SAM trial required')
    profile=json.loads((trial/'calibration.local.json').read_text());obs=json.loads((trial/'observations.local.json').read_text());summary=json.loads((trial/'summary.local.json').read_text())
    review_path=trial/'human-transfer-review.accepted.local.json';review=json.loads(review_path.read_text())
    if not check_mask_review(review,trial.name,profile,obs):p.error('Review or correct each target first')
    if summary['seed_identity_collision']:p.error('Seed identity collision')
    session=json.loads((ROOT/'local'/profile['source_session']/'session.local.json').read_text());frames=sorted(session['frames'],key=lambda f:f['timestamp_sec']);h,w=frames[0]['height'],frames[0]['width']
    out=ROOT/'local'/('money-context-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
    write_json(out/'protocol.local.json',{'parameters':PROTOCOL,'source_trial':trial.name,'mask_sha256':sha(trial/'masks.local.npz'),
                 'review_sha256':sha(review_path),'code_sha256':sha(Path(__file__)),'module_sha256':sha(ROOT/'scene_mvp/money_contacts.py'),
                 'independent_evaluation':False,'development_video_human_direction_already_known':True,
                 'expected_direction_passed_to_inference':False,'frozen_method_output_not_modified':True})
    initial={k:summary['initialization'][k]['mask_area_fraction']*h*w for k in ('cash','cashier_hand','client_hand')}
    rows=[]
    with np.load(trial/'masks.local.npz') as z:
        for i,(f,old) in enumerate(zip(frames,obs['timeline'])):
            if abs(old['timestamp_sec']-f['timestamp_sec'])>.001:raise ValueError('Timestamp mismatch')
            raw={k:np.unpackbits(z[k][i],axis=-1,count=w).astype(bool) for k in initial};valid={}
            for k,m in raw.items():
                n=int(m.sum())
                if max(PROTOCOL['minimum_mask_pixels'],initial[k]*PROTOCOL['minimum_area_relative_to_seed'])<=n<=initial[k]*PROTOCOL['maximum_area_relative_to_seed']:valid[k]=m
            collision=any(np.count_nonzero(a&b)/max(1,np.count_nonzero(a|b))>PROTOCOL['maximum_mask_iou'] for j,a in enumerate(valid.values()) for b in list(valid.values())[j+1:])
            row={'timestamp_sec':f['timestamp_sec'],'targets':old['targets'],'cash_observed':'cash' in valid and not collision,
                 'hand_proximity':{'cashier':'unknown','client':'unknown'},'identity_collision':collision,
                 'role_owner_observed':old['role_owner_observed'],'reason':'mask_identity_collision' if collision else None}
            if row['cash_observed']:
                yy,xx=np.nonzero(valid['cash']);diag=max(1,float(np.hypot(xx.max()-xx.min()+1,yy.max()-yy.min()+1)))
                for role,k in [('cashier','cashier_hand'),('client','client_hand')]:
                    if k not in valid or not old['role_owner_observed'][role]:continue
                    d=float(cv2.distanceTransform((~valid[k]).astype(np.uint8),cv2.DIST_L2,3)[valid['cash']].min()/diag)
                    row.setdefault('hand_distances',{})[role]=d
                    row['hand_proximity'][role]='near' if d<=PROTOCOL['near_relative_to_cash_size'] else 'far' if d>=PROTOCOL['far_relative_to_cash_size'] else 'ambiguous'
            a,b=row['hand_proximity'].values();row['relation']='both_near' if a==b=='near' else 'cashier_near_partial_context' if a=='near' else 'client_near_partial_context' if b=='near' else 'unknown' if 'unknown' in (a,b) else 'neither_near'
            if not row['cash_observed']:row['reason']='cash_mask_unknown_or_rejected'
            rows.append(row)
    events=candidates(rows)
    result={'schema_version':'money-contact-context/1','source_trial':trial.name,'source_session':profile['source_session'],'source_video_sha256':profile['source_video_sha256'],
            'roles':profile['roles'],'timeline':rows,'transfer_candidates':events,'independent_evaluation':False,'direction_established':False,'is_legal_verdict':False,'approved_for_rule_engine':False}
    write_json(out/'motion-observations.local.json',result);write_json(out/'summary.local.json',{'context_candidates':len(events),'candidates':events,'direction_established':False,'independent_evaluation':False})
    page=build(trial,out);text=page.read_text();text=text.replace('<h1>','<aside>Новый исследовательский вариант после проверки Х-2. Метка направления этого ролика уже известна разработчику, поэтому это не независимая оценка. Здесь проверяется порядок близости двух кистей, а не владение. Потеря банкнот явно разрывает доказательство непрерывности предмета; такое окно нельзя автоматически считать передачей.</aside><h1>',1);page.write_text(text)
    print('MONEY_CONTEXT_READY:',page);print(json.dumps({'context_candidates':len(events),'candidates':events,'direction_established':False},ensure_ascii=False))

if __name__=='__main__':main()
