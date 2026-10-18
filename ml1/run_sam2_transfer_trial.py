"""Local three-target SAM tracking and conservative transfer proximity hypotheses."""
import argparse,base64,datetime,gc,hashlib,html,json,os,sys,time
from pathlib import Path
os.environ.update(HF_HUB_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',PYTORCH_ENABLE_MPS_FALLBACK='1')
from run_ollama_trial import ROOT,write_json
from scene_mvp.transfer_events import TARGETS,validate,infer,require_two_party_context
from scene_mvp.segmentation_prompts import choose_point_consistent

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--calibration',type=Path,required=True);p.add_argument('--reuse-reviewed-hands',type=Path);args=p.parse_args()
 profile=json.loads(args.calibration.read_text());source=(ROOT/'local'/profile['source_session']).resolve()
 if not source.is_relative_to((ROOT/'local').resolve()):p.error('Local session required')
 session=json.loads((source/'session.local.json').read_text());validate(profile,session);frames=sorted(session['frames'],key=lambda f:f['timestamp_sec'])
 context_path=source/'human-scene-context.accepted.local.json'
 require_two_party_context(json.loads(context_path.read_text()) if context_path.exists() else None,session)
 reuse=None
 if args.reuse_reviewed_hands:
  reuse=args.reuse_reviewed_hands.resolve()
  if not reuse.is_relative_to((ROOT/'local').resolve()):p.error('Local previous trial required')
  old=json.loads((reuse/'calibration.local.json').read_text());review=json.loads((reuse/'human-transfer-review.accepted.local.json').read_text())
  if old['source_video_sha256']!=profile['source_video_sha256'] or old['source_session']!=profile['source_session'] or old['roles']!=profile['roles']:p.error('Reused hands video/roles mismatch')
  if review['review_session']!=reuse.name or review['source_video_sha256']!=profile['source_video_sha256'] or review['source_session']!=profile['source_session'] or review['review_scope']!='user_reviewed_frames_only':p.error('Reused hands review mismatch')
  if any(old['targets'][k]!=profile['targets'][k] or review['human_target_reviews'][k]!='correct_on_reviewed_frames' for k in ('cashier_hand','client_hand')):p.error('Changed or unreviewed hand target')
  binding=profile.get('correction_source_review')
  if binding and (binding['review_session']!=reuse.name or binding['accepted_review_sha256']!=hashlib.sha256((reuse/'human-transfer-review.accepted.local.json').read_bytes()).hexdigest()):p.error('Correction review binding mismatch')
 runtime=json.loads((ROOT/'local/runtime/sam2-runtime.local.json').read_text());weights=Path(runtime['weights_path'])
 if hashlib.sha256(weights.read_bytes()).hexdigest()!=runtime['weights_sha256']:p.error('Checkpoint changed')
 if reuse and json.loads((reuse/'runtime.local.json').read_text())['weights_sha256']!=runtime['weights_sha256']:p.error('Reused hands model mismatch')
 sys.path.insert(0,str(ROOT/'local/runtime/edgetam-deps'));sys.path.insert(0,runtime['source_path'])
 import cv2,numpy as np,torch
 from sam2.build_sam import build_sam2_video_predictor
 from sam2.sam2_image_predictor import SAM2ImagePredictor
 torch.set_num_threads(2);device='mps' if torch.backends.mps.is_available() else 'cpu'
 out=ROOT/'local'/('sam2-transfer-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir();(out/'video_frames').mkdir();(out/'overlays').mkdir()
 print('SAM2_TRANSFER_TRIAL:',out,flush=True);start=time.monotonic();protocol={'near_distance_relative_to_object_size':.2,'exclusive_other_hand_min_distance':.5,'ambiguous_mask_iou':.65,'stable_exclusive_sec':.5,'max_gap_sec':.75,'max_transition_sec':3,'minimum_object_displacement_relative_to_size':.25,'expected_direction_used':False,'all_original_frames_processed':False,'source_revision':runtime['source_revision'],'weights_sha256':runtime['weights_sha256']}
 write_json(out/'protocol.local.json',protocol);write_json(out/'calibration.local.json',profile);write_json(out/'status.json',{'status':'running','phase':'seed_preflight','device':device})
 try:
  for i,f in enumerate(frames):
   path=(source/f['file']).resolve()
   if not path.is_relative_to(source):raise ValueError('Frame outside source')
   os.link(path,out/'video_frames'/f'{i:05d}.jpg')
  predictor=build_sam2_video_predictor('configs/sam2.1/sam2.1_hiera_t.yaml',str(weights),device=device,apply_postprocessing=False)
  anchors={k:min(range(len(frames)),key=lambda i:abs(frames[i]['timestamp_sec']-profile['targets'][k]['timestamp_sec'])) for k in TARGETS}
  h,w=frames[0]['height'],frames[0]['width'];seed_masks={};seed_meta={};image_predictor=SAM2ImagePredictor(predictor)
  def mask_iou(a,b):
   union=np.count_nonzero(a|b);return float(np.count_nonzero(a&b)/union) if union else 0.
  def geometry_point(k):
   b=profile['targets'][k]['bbox'];t=profile['targets'][k]['timestamp_sec'];others=[v['bbox'] for n,v in profile['targets'].items() if n!=k and abs(v['timestamp_sec']-t)<.001]
   candidates=[]
   for fx in np.linspace(.08,.92,13):
    for fy in np.linspace(.08,.92,13):
     q=[b[0]+fx*(b[2]-b[0]),b[1]+fy*(b[3]-b[1])]
     if any(v[0]<=q[0]<=v[2] and v[1]<=q[1]<=v[3] for v in others):continue
     score=min(fx,1-fx,fy,1-fy);candidates.append((score,q))
   q=max(candidates,key=lambda x:x[0])[1] if candidates else [(b[0]+b[2])/2,(b[1]+b[3])/2]
   return np.array([q[0]*w,q[1]*h],dtype=np.float32)
  automatic_points={k:geometry_point(k) for k in TARGETS}
  def seed(k,with_points=False,target=None):
   target=target or profile['targets'][k];b=target['bbox'];human_points=target.get('points',[]);frame_index=min(range(len(frames)),key=lambda i:abs(frames[i]['timestamp_sec']-target['timestamp_sec']))
   xs=[b[0],b[2]]+[v['xy'][0] for v in human_points];ys=[b[1],b[3]]+[v['xy'][1] for v in human_points]
   x1,y1,x2,y2=[max(0,round((min(xs)-.1)*w)),max(0,round((min(ys)-.1)*h)),min(w,round((max(xs)+.1)*w)),min(h,round((max(ys)+.1)*h))]
   image=cv2.imread(str(out/'video_frames'/f'{frame_index:05d}.jpg'));ok,encoded=cv2.imencode('.jpg',image[y1:y2,x1:x2])
   if not ok:raise ValueError('Seed encode failed')
   crop=cv2.imdecode(encoded,cv2.IMREAD_COLOR);image_predictor.set_image(cv2.cvtColor(crop,cv2.COLOR_BGR2RGB));box=np.array([b[0]*w-x1,b[1]*h-y1,b[2]*w-x1,b[3]*h-y1],np.float32);kw={};point_record=[]
   if human_points:
    pts=np.array([[v['xy'][0]*w,v['xy'][1]*h] for v in human_points],np.float32);labels=np.array([v['label'] for v in human_points],np.int32)
    point_record=[{'point_px':q.tolist(),'label':int(label),'source':'human_click_on_visible_target_or_distractor'} for q,label in zip(pts,labels)]
    kw={'point_coords':pts-np.array([x1,y1],np.float32),'point_labels':labels}
   elif with_points:
    pts=[automatic_points[k]];labels=[1]
    for other in TARGETS:
     if other==k or anchors[other]!=anchors[k]:continue
     q=automatic_points[other]
     if np.linalg.norm(q-pts[0])>2:pts.append(q);labels.append(0)
    if k!='cash' and anchors['cash']==anchors[k]:
     b2=profile['targets']['cash']['bbox'];q=np.array([(b2[0]+b2[2])*w/2,(b2[1]+b2[3])*h/2],np.float32)
     if np.linalg.norm(q-pts[0])>2:pts.append(q);labels.append(0)
    point_record=[{'point_px':q.tolist(),'label':lab,'source':'automatic_geometry_heuristic_not_human_point'} for q,lab in zip(pts,labels)]
    kw={'point_coords':np.array(pts)-np.array([x1,y1],np.float32),'point_labels':np.array(labels,np.int32)}
   masks,scores,_=image_predictor.predict(box=box,multimask_output=True,**kw);methods=['box_and_points' if human_points else 'box']*len(scores);checks=[]
   def check_points(mask):
    return [bool(mask[min(mask.shape[0]-1,max(0,round(v['xy'][1]*h-y1))),min(mask.shape[1]-1,max(0,round(v['xy'][0]*w-x1)))])==bool(v['label']) for v in human_points]
   if human_points:
    checks=[check_points(m) for m in masks]
    # A higher predicted SAM IoU does not override a user's positive/negative click.
    if not all(checks[int(np.argmax(scores))]):
     alt,alt_scores,_=image_predictor.predict(multimask_output=True,**kw);masks=np.concatenate([masks,alt]);scores=np.concatenate([scores,alt_scores]);methods+=['points_only_after_box_conflict']*len(alt_scores);checks += [check_points(m) for m in alt]
    selected=choose_point_consistent(scores,checks)
   else:selected=int(np.argmax(scores))
   full=np.zeros((h,w),bool)
   if selected is not None:full[y1:y2,x1:x2]=masks[selected].astype(bool)
   image_predictor.reset_predictor()
   return full,{'anchor_sec':frames[frame_index]['timestamp_sec'],'crop_px':[x1,y1,x2,y2],'model_iou_score_uncalibrated':float(scores[selected]) if selected is not None else None,'initialization':methods[selected] if selected is not None else 'no_point_consistent_candidate','points':point_record,'mask_area_fraction':float(full.mean()),'human_points_consistent':all(checks[selected]) if human_points and selected is not None else None,'candidate_selection':'highest_model_score_among_point_consistent_candidates' if human_points else 'highest_model_score','candidate_checks':[{'method':method,'score_uncalibrated':float(score),'all_points_consistent':all(c)} for method,score,c in zip(methods,scores,checks)]}
  with torch.inference_mode():
   for k in TARGETS:seed_masks[k],seed_meta[k]=seed(k)
   def collisions(masks):return [{'targets':[a,b],'iou':mask_iou(masks[a],masks[b])} for i,a in enumerate(TARGETS) for b in TARGETS[i+1:] if anchors[a]==anchors[b]]
   seed_attempts=[{'method':'box','pairwise_mask_iou':collisions(seed_masks),'targets':seed_meta}]
   if any(v['iou']>.65 for v in collisions(seed_masks)):
    alternative={};meta={}
    for k in TARGETS:alternative[k],meta[k]=seed(k,True)
    seed_attempts.append({'method':'box_with_automatic_separation_points','pairwise_mask_iou':collisions(alternative),'targets':meta})
    if max((x['iou'] for x in collisions(alternative)),default=0)<max((x['iou'] for x in collisions(seed_masks)),default=0) and all(m.any() for m in alternative.values()):seed_masks,seed_meta=alternative,meta
   correction_seeds=[]
   for target in profile.get('cash_corrections',[]):
    m,meta=seed('cash',target=target);idx=min(range(len(frames)),key=lambda i:abs(frames[i]['timestamp_sec']-target['timestamp_sec']));correction_seeds.append((idx,m,meta))
   del image_predictor;gc.collect()
   unresolved=any(v['iou']>.65 for v in collisions(seed_masks)) or any(not m.any() for m in seed_masks.values()) or any(not m.any() for _,m,_ in correction_seeds)
   write_json(out/'seed-preflight.local.json',{'attempts':seed_attempts,'selected':seed_meta,'cash_corrections':[meta for _,_,meta in correction_seeds],'unresolved_identity_collision':unresolved,'human_identity_verified':False});print('SEED_PREFLIGHT:',json.dumps({'unresolved_identity_collision':unresolved,'pairwise_mask_iou':collisions(seed_masks)}),flush=True)
   tracks={k:{} for k in TARGETS}
   if reuse:
    with np.load(reuse/'masks.local.npz') as cached:
     for k in ('cashier_hand','client_hand'):
      unpacked=np.unpackbits(cached[k],axis=-1,count=w).astype(bool)
      if unpacked.shape!=(len(frames),h,w):raise ValueError('Reused hand shape mismatch')
      tracks[k]={i:m for i,m in enumerate(unpacked)}
   if not unresolved:
    for k in TARGETS:
     if reuse and k!='cash':print('REUSED_REVIEWED_HAND_TRACK:',k,flush=True);continue
     print('TRACKING_TARGET:',k,flush=True);state=predictor.init_state(str(out/'video_frames'),offload_video_to_cpu=True,offload_state_to_cpu=True);predictor.add_new_mask(state,frame_idx=anchors[k],obj_id=1,mask=seed_masks[k])
     if k=='cash':
      for idx,m,_ in correction_seeds:predictor.add_new_mask(state,frame_idx=idx,obj_id=1,mask=m)
     start_idx=min([anchors[k]]+[i for i,_,_ in correction_seeds]) if k=='cash' else anchors[k]
     for reverse in (False,True):
      for index,_,logits in predictor.propagate_in_video(state,start_frame_idx=start_idx,reverse=reverse):
       tracks[k][index]=(logits[0,0]>0).cpu().numpy()
       if len(tracks[k])%10==0:write_json(out/'status.json',{'status':'running','phase':'tracking','target':k,'frames':len(tracks[k]),'total_frames':len(frames),'device':device});print('TRANSFER_TRACKED:',k,len(tracks[k]),'/',len(frames),flush=True)
     del state;gc.collect()
     if device=='mps':torch.mps.empty_cache()
   else:
    for k in TARGETS:tracks[k][anchors[k]]=seed_masks[k]
  rows=[];cards=[];replay=[];labels={'cash':'Банкноты','cashier_hand':'Кисть кассира','client_hand':'Кисть клиента'};colors={'cash':(0,210,80),'cashier_hand':(255,110,20),'client_hand':(0,150,255)}
  for i,f in enumerate(frames):
   row={'timestamp_sec':f['timestamp_sec'],'targets':{},'relation':'unknown','cash_human_prompt_frame':i in [anchors['cash']]+[j for j,_,_ in correction_seeds]};valid={};image=cv2.imread(str(source/f['file']))
   for k in TARGETS:
    m=tracks[k].get(i);b=None;area=0;seed_box=profile['targets'][k]['bbox']
    if m is not None and m.any():
     yy,xx=np.nonzero(m);area=float(m.mean());b=[float(xx.min()/w),float(yy.min()/h),float((xx.max()+1)/w),float((yy.max()+1)/h)]
    okay=b is not None and .0002<=area<=max(.03,4*(seed_box[2]-seed_box[0])*(seed_box[3]-seed_box[1]))
    row['targets'][k]={'state':'mask_observed' if okay else 'unknown','bbox':b if okay else None,'mask_area_fraction':area,'target_kind_source':'human_visual_prompt'}
    if okay:
     valid[k]=m;tint=image.copy();tint[m]=colors[k];image=cv2.addWeighted(image,.7,tint,.3,0);cv2.rectangle(image,(round(b[0]*w),round(b[1]*h)),(round(b[2]*w),round(b[3]*h)),colors[k],1)
   if len(valid)==3 and not unresolved:
    pair_iou=[mask_iou(valid[a],valid[b]) for j,a in enumerate(TARGETS) for b in TARGETS[j+1:]];row['max_target_mask_iou']=max(pair_iou)
    b=row['targets']['cash']['bbox'];diag=max(1,float(np.hypot((b[2]-b[0])*w,(b[3]-b[1])*h)));row['cash_center_px']=[(b[0]+b[2])*w/2,(b[1]+b[3])*h/2];row['cash_diagonal_px']=diag
    if max(pair_iou)<=.65:
     distances={}
     for k in ['cashier_hand','client_hand']:
      dt=cv2.distanceTransform((~valid[k]).astype(np.uint8),cv2.DIST_L2,3);distances[k]=float(dt[valid['cash']].min()/diag)
     row['hand_distance_relative_to_cash_size']=distances;a=distances['cashier_hand'];b2=distances['client_hand']
     row['relation']='both_near' if a<=.2 and b2<=.2 else 'cashier_near' if a<=.2 and b2>=.5 else 'client_near' if b2<=.2 and a>=.5 else 'neither_near' if a>=.5 and b2>=.5 else 'ambiguous'
   filename=f'overlays/{i:03d}.jpg';cv2.imwrite(str(out/filename),image);uri='data:image/jpeg;base64,'+base64.b64encode((out/filename).read_bytes()).decode();replay.append({'time':f['timestamp_sec'],'image':uri,'relation':row['relation']});cards.append('<article><h3>'+f"{f['timestamp_sec']:.3f}"+' с</h3><img src="'+uri+'"><p>'+row['relation']+'</p></article>');rows.append(row)
  events=infer(rows);summary={'model':'SAM 2.1 Hiera Tiny','device':device,'frames':len(frames),'targets':{k:{'mask_observed_frames':sum(r['targets'][k]['state']=='mask_observed' for r in rows),'anchor_sec':frames[anchors[k]]['timestamp_sec']} for k in TARGETS},'seed_identity_collision':unresolved,'initialization':seed_meta,'transfer_candidates':len(events),'sample_fps_nominal':2,'full_frame_tracking':True,'separate_state_per_target':True,'expected_direction_used':False,'automatic_currency_classification':False,'possession_established':False,'approved_for_rule_engine':False,'elapsed_sec':round(time.monotonic()-start,2)}
  summary.update(cash_correction_seeds=[meta for _,_,meta in correction_seeds],reused_hand_trial=reuse.name if reuse else None,reused_hands_review_scope='user_reviewed_frames_only' if reuse else None,independent_evaluation=False)
  write_json(out/'observations.local.json',{'schema_version':1,'status':'needs_seed_review' if unresolved else 'partial','timeline':rows,'transfer_candidates':events,'roles':profile['roles'],'is_legal_verdict':False});write_json(out/'summary.local.json',summary);write_json(out/'runtime.local.json',runtime)
  np.savez_compressed(out/'masks.local.npz',**{k:np.packbits(np.array([tracks[k].get(i,np.zeros((h,w),bool)) for i in range(len(frames))]),axis=-1) for k in TARGETS})
  description='Начальные маски разных целей совпадают. Нужны подсказки на кадрах, где банкноты и кисти различимы отдельно; направление не вычислялось.' if unresolved else 'Каждая цель отслеживалась отдельно по всему кадру и всей длительности с выборкой 2 кадра/с. Близость кисти к деньгам не доказывает владение. Потеря любой цели или почти одинаковые маски дают неизвестность.'
  candidate_text=''.join('<li>'+f"{e['start_sec']:.3f}–{e['end_sec']:.3f}"+' с: '+({'cashier_to_client':'кассир → клиент','client_to_cashier':'клиент → кассир'}[e['direction']])+' — гипотеза по близости и движению, требует проверки.</li>' for e in events) or '<li>Надёжная по заданным условиям гипотеза не выделена. Это не означает отсутствия передачи.</li>'
  seed_cards=''.join('<h3>'+', '.join(labels[k] for k in TARGETS if anchors[k]==i)+' · '+str(frames[i]['timestamp_sec'])+' с</h3>'+cards[i] for i in sorted(set(anchors.values())))
  data=json.dumps(replay,ensure_ascii=False).replace('<','\\u003c');review_data=json.dumps({'schema_version':1,'review_session':out.name,'source_session':session['session_id'],'source_video_sha256':session['source_video_sha256'],'transfer_candidates':events,'summary':summary,'approved_for_rule_engine':False},ensure_ascii=False).replace('<','\\u003c')
  selectors=''.join('<label>'+labels[k]+' — маска верна? <select id="review-'+k+'"><option value="">Выбери</option><option value="correct_on_reviewed_frames">Да</option><option value="incorrect_on_reviewed_frames">Нет / местами неверно</option><option value="unclear">Неясно</option></select></label>' for k in TARGETS)
  script='const frames='+data+',review='+review_data+';let index=0,timer=null;function show(i){index=Math.max(0,Math.min(frames.length-1,i));document.getElementById("player").src=frames[index].image;document.getElementById("time").value=index;document.getElementById("info").textContent=frames[index].time.toFixed(3)+" с · "+frames[index].relation;}function play(){if(timer){clearInterval(timer);timer=null;return;}timer=setInterval(()=>show((index+1)%frames.length),500)}function save(){const checks=Object.fromEntries(["cash","cashier_hand","client_hand"].map(k=>[k,document.getElementById("review-"+k).value]));if(Object.values(checks).some(v=>!v)){document.getElementById("status").textContent="Выбери ответ для каждой цели";return;}const blob=new Blob([JSON.stringify({...review,human_target_reviews:checks,review_scope:"user_reviewed_frames_only"},null,2)],{type:"application/json"}),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=review.review_session+"-transfer-review.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),10000)}show(0);'
  page='<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; script-src \'unsafe-inline\'; connect-src \'none\'"><title>SAM: банкноты и руки</title><style>body{font:18px system-ui;max-width:1200px;margin:30px auto;padding:20px}img{width:100%}#player{height:65vh;object-fit:contain}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:16px}article{padding:12px;background:#edf2f8}button,select,input{font:inherit;padding:10px;margin:10px}label{display:block}</style><h1>SAM: банкноты и две кисти · '+html.escape(session['source_name'])+'</h1><p>Зелёный — банкноты, синий — кисть кассира (ID '+str(profile['roles']['cashier_ids'][0])+'), оранжевый — кисть клиента (ID '+str(profile['roles']['client_ids'][0])+'). Типы и принадлежность подсказок заданы человеком. Модель не получает правильное направление передачи.</p><p>'+description+'</p><h2>Гипотезы передачи</h2><ul>'+candidate_text+'</ul><img id="player"><p id="info"></p><button onclick="play()">Воспроизвести / пауза</button><input id="time" type="range" min="0" max="'+str(len(frames)-1)+'" value="0" oninput="show(Number(this.value))"><details open><summary>Опорные кадры — проверь именно кисти и деньги</summary><div class="grid">'+seed_cards+'</div></details><details><summary>Все кадры</summary><div class="grid">'+''.join(cards)+'</div></details>'+selectors+'<button onclick="save()">Сохранить проверку трёх масок</button><p id="status"></p><script>'+script+'</script></html>'
  (out/'report.html').write_text(page,encoding='utf-8')
  from build_transfer_review import build
  summary=build(out)
  write_json(out/'status.json',{'status':'needs_seed_review' if unresolved else 'completed','device':device,'approved_for_rule_engine':False});print('SAM2_TRANSFER_REPORT_READY:',out/'report.html',flush=True);print(json.dumps(summary),flush=True)
 except Exception as e:write_json(out/'status.json',{'status':'failed','error_type':type(e).__name__,'error':str(e)[:1000]});raise

if __name__=='__main__':main()
