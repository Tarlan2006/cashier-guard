"""Show four representative human-labeled door crops and their full-frame context locally."""
import argparse,base64,datetime,html,io,json
from pathlib import Path
from PIL import Image,ImageDraw
from run_ollama_trial import ROOT,write_json

def uri(image):
 b=io.BytesIO();image.save(b,format='JPEG',quality=95);return 'data:image/jpeg;base64,'+base64.b64encode(b.getvalue()).decode()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profiles',type=Path,nargs='+',required=True);args=p.parse_args();folder=ROOT/'local'/('door-audit-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));folder.mkdir();cards='';records=[]
 for file in args.profiles:
  profile=json.loads(file.read_text());session_dir=(ROOT/'local'/profile['source_session']).resolve()
  if not session_dir.is_relative_to((ROOT/'local').resolve()):raise ValueError('Invalid session')
  session=json.loads((session_dir/'session.local.json').read_text());lookup={round(r['timestamp_sec'],3):r for r in session['frames']};labels=sorted(profile['door_frame_labels'],key=lambda x:x['timestamp_sec'])
  for state in ['closed','open']:
   segments=[];current=[]
   for label in labels:
    if label['state']==state:
     if current and label['timestamp_sec']-current[-1]['timestamp_sec']>1.01:segments.append(current);current=[]
     current.append(label)
    elif current:segments.append(current);current=[]
   if current:segments.append(current)
   selected=max(segments,key=len);label=selected[len(selected)//2];frame=lookup[round(label['timestamp_sec'],3)]
   image=Image.open(session_dir/frame['file']).convert('RGB');w,h=image.size;b=profile['zones']['door_zone'];xy=[round(b[0]*w),round(b[1]*h),round(b[2]*w),round(b[3]*h)];crop=image.crop(xy);context=image.copy();ImageDraw.Draw(context).rectangle(xy,outline='#0066ff',width=3)
   identifier=str(len(records)+1);records.append({'id':identifier,'video':session['source_name'],'timestamp_sec':label['timestamp_sec'],'human_state':state,'zone':b,'source_session':profile['source_session']})
   title='Закрыта' if state=='closed' else 'Открыта';cards+='<article><h2>Пример '+identifier+': '+html.escape(session['source_name'])+' · '+str(round(label['timestamp_sec'],3))+' с</h2><p><b>Твоя метка: '+title+'</b></p><div class="pair"><div><p>Исходный кадр; синяя рамка — выделенная область</p><img src="'+uri(context)+'"></div><div><p>Фактический участок модели</p><img src="'+uri(crop)+'"></div></div></article>'
 write_json(folder/'audit-records.local.json',{'examples':records,'labels_modified':False,'model_enabled':False})
 (folder/'report.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'"><style>body{font:18px system-ui;max-width:1200px;margin:30px auto;padding:20px}article{background:#eef3f8;padding:20px;margin:20px 0}.pair{display:grid;grid-template-columns:1fr 1fr;gap:20px}img{width:100%;max-height:650px;object-fit:contain}</style><h1>Проверка четырёх примеров двери</h1><p>Проверь, что синяя область содержит нужную дверь и её положение различимо, а подписи открыта/закрыта верны во всех четырёх примерах. Примеры выбраны из середины длинных размеченных интервалов. Предсказаний модели здесь нет; метки не изменены.</p><p>Проверка модели между видео не пройдена: модель не подключена к сигналам. Ошибки модели сами по себе не доказывают ошибку разметки.</p>'+cards,encoding='utf-8')
 print('DOOR_AUDIT_READY:',folder/'report.html');print(json.dumps({'examples':len(records),'labels_modified':False}))
if __name__=='__main__':main()
