"""Build a local side-by-side review. Never print captions or image bytes."""
import argparse
import base64
import datetime
import html
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def read_trial(folder):
    folder=folder.resolve()
    if not folder.is_relative_to((ROOT/'local').resolve()):
        raise ValueError('Use local trial folders only')
    status=json.loads((folder/'status.json').read_text())
    frames=json.loads((folder/'frames.json').read_text())['frames']
    answers=json.loads((folder/'captions.local.json').read_text())['captions']
    if len(frames)!=len(answers):raise ValueError('Incomplete frame descriptions')
    return folder,status,frames,answers


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    args=parser.parse_args()
    old,old_status,old_frames,old_answers=read_trial(args.baseline)
    new,new_status,new_frames,new_answers=read_trial(args.candidate)
    if old_status.get('source_name')!=new_status.get('source_name'):
        raise ValueError('Comparison requires the same source video')
    folder=ROOT/'local'/('comparison-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(parents=True)
    esc=html.escape
    def image_path(base,name):
        path=(base/name).resolve()
        if not path.is_relative_to((ROOT/'local').resolve()) or not path.is_file():raise ValueError('Invalid local image path')
        mime = 'image/jpeg' if path.suffix.lower() in ('.jpg', '.jpeg') else 'image/png'
        return 'data:'+mime+';base64,'+base64.b64encode(path.read_bytes()).decode('ascii')
    cards=[];matched=0
    for frame,answer in zip(new_frames,new_answers):
        timestamp=frame['timestamp_sec']
        choices=[i for i,f in enumerate(old_frames) if abs(f['timestamp_sec']-timestamp)<.04]
        old_text='Для этого момента нет описания прежней модели.'
        if choices:
            i=min(choices,key=lambda i:abs(old_frames[i]['timestamp_sec']-timestamp))
            old_text=old_answers[i]['response'];matched+=1
        context=frame.get('context_file',frame['file'])
        crop=(f'<details><summary>Область деталей, переданная модели</summary><img src="{image_path(new,frame["file"])}" alt="Детали"></details>'
              if frame.get('context_file') else '')
        cards.append(f'''<article><h2>{timestamp:.3f} с</h2>
<img src="{image_path(new,context)}" alt="Кадр для проверки">{crop}
<div class="columns"><section><h3>Предыдущая модель</h3><pre>{esc(old_text)}</pre></section>
<section><h3>Новая модель</h3><pre>{esc(answer['response'])}</pre></section></div></article>''')
    sequence_sections=[]
    for name,base in [('Предыдущая модель',old),('Новая модель',new)]:
        p=base/'sequence.local.json'
        text=json.loads(p.read_text())['response'] if p.is_file() else 'Совместного сравнения нет.'
        sequence_sections.append(f'<section><h3>{name}</h3><pre>{esc(text)}</pre></section>')
    document=f'''<!doctype html><html lang="ru"><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Сравнение локальных моделей</title>
<style>body{{font:16px system-ui;max-width:1100px;margin:32px auto;padding:0 24px;background:#f5f7fb;color:#17212b}}
article,section{{background:white;padding:20px;border-radius:12px;margin:16px 0}}img{{max-width:100%;max-height:650px}}
.columns{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px}}pre{{white-space:pre-wrap;line-height:1.6;overflow-wrap:anywhere}}
.note{{background:#fff0ce;padding:20px;border-radius:12px;line-height:1.6}}</style>
<h1>Сравнение локальных моделей</h1>
<p>Источник: {esc(new_status.get('source_name',''))}</p>
<p>{esc(old_status['model'])} → {esc(new_status['model'])}</p>
<p class="note">Сравниваются две настройки обработки одного эпизода: модель, запрос и область изображения могли измениться.
Таймкод выбран заранее. Это не оценка самостоятельного поиска нарушений по всем видео.
Проверьте предметы, положение рук, неподтверждённые детали и соответствие описаний изменениям между кадрами.
Ответы обеих моделей остаются черновыми до проверки человеком.</p>
<h2>Совместное сравнение последовательности</h2><div class="columns">{''.join(sequence_sections)}</div>
{''.join(cards)}</html>'''
    (folder/'report.html').write_text(document,encoding='utf-8')
    (folder/'comparison.json').write_text(json.dumps({'baseline':str(old),'candidate':str(new),
        'matched_frame_count':matched,'candidate_frame_count':len(new_frames),'review_status':'needs_human_review'},indent=2))
    print('Comparison report:',folder/'report.html')
    print('Matched timestamps:',matched,'candidate frames:',len(new_frames))


if __name__=='__main__':main()
