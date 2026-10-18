"""Import user-supplied PDF annotations as versioned references, never model input."""
import argparse,datetime,hashlib,json,re
from collections import Counter
from pathlib import Path
import pdfplumber

ROOT=Path(__file__).resolve().parent

def norm(value):return value.replace('Х','X')

def extract(path,manifest):
 records=[]
 lookup={norm(v['id']):v for v in manifest['videos']}
 with pdfplumber.open(path) as doc:
  for number,page in enumerate(doc.pages,1):
   text=page.extract_text() or ''
   blocks=list(re.finditer(r'(?m)^([XХ]-\d+)\s*$',text))
   for i,match in enumerate(blocks):
    body=text[match.end():blocks[i+1].start() if i+1<len(blocks) else len(text)]
    body=re.sub(r'\n\d+\s*$','',body).strip()
    kind=re.search(r'(?m)^Тип:\s*(.+)$',body)
    timestamp=re.search(r'(?m)^Время:\s*(.+)$',body)
    description=re.search(r'Описание:\s*(.+)',body,re.S)
    if not all((kind,timestamp,description)):raise ValueError('Incomplete PDF entry')
    identifier=norm(match.group(1));video=lookup[identifier]
    if timestamp.group(1)=='—':seconds=None
    else:
     t=re.fullmatch(r'(\d+(?:[.,]\d+)?)\s*с',timestamp.group(1))
     if not t:raise ValueError('Unrecognized timestamp')
     seconds=float(t.group(1).replace(',','.'))
     if not 0<=seconds<video['metadata']['duration_sec']:raise ValueError('Timestamp outside video')
    title=kind.group(1)
    risk='high' if title.endswith('высокий риск.') else 'moderate' if title.endswith('умеренный риск.') else 'not_identified' if 'Нарушение не выявлено' in title else None
    if risk is None:raise ValueError('Unrecognized risk category')
    description=' '.join(description.group(1).split())
    records.append({'video_id':identifier,'filename':video['filename'],'video_sha256':video['sha256'],
       'source_page':number,'reference_timestamp_sec':seconds,'annotation_type':title,
       'description':description,'risk_annotation':risk,'legal_violation_established':False,
       'source_kind':'user_supplied_pdf_annotation','review_status':'not_independently_video_verified',
       'original_dataset_label':video['label']})
 if len({r['video_id'] for r in records})!=len(records):raise ValueError('Duplicate video entry')
 if {r['video_id'] for r in records}!=set(lookup):raise ValueError('PDF and dataset coverage differ')
 return records

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pdf',type=Path,required=True);args=p.parse_args()
 manifest=json.loads((ROOT/'outputs/forte_dataset_manifest.json').read_text())
 rows=extract(args.pdf,manifest);digest=hashlib.sha256(args.pdf.read_bytes()).hexdigest()
 out=ROOT/'local'/('pdf-annotations-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
 result={'schema_version':1,'source_file':str(args.pdf.resolve()),'source_sha256':digest,
         'purpose':'reference_annotations_for_review_and_evaluation_only',
         'previous_annotations_overwritten':False,'expected_labels_must_not_be_model_input':True,
         'split_policy':'group_by_video_sha256; duplicate files must remain in same split',
         'risk_is_not_legal_verdict':True,'records':rows}
 (out/'annotations.local.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
 notes='Новая версия пользовательской разметки из PDF. Предыдущая разметка сохранена.\nЦвет — предварительный риск, не юридический вывод. Описания не проверены повторным просмотром видео.\nX-1: возврат части суммы, причина неизвестна; не использовать прежнюю метку «присвоение» как истину.\nX-11/X-22: возможный ключ в замке; не подменять меткой «компьютер не заблокирован».\nX-30/X-33: возможный посторонний доступ; открытая дверь не доказывает отсутствие допуска.\nX-46: напиток за столом; не распознавание штампа.\nX-4/X-47 и X-5/X-48 — одинаковые видео; не разносить по train/test.\nЗелёные строки: в этой разметке нарушение не выявлено; это не гарантия отсутствия всех нарушений.\nПриоритет разработки: X-18/X-19 посетители; X-20/X-21 дверца шкафа; X-15/X-16 сумка.\nКлюч, экран, банкноты, пересчёт и документы требуют отдельной проверки различимости.\n'
 (out/'review-notes.txt').write_text(notes)
 print('PDF_ANNOTATIONS_IMPORTED:',out)
 print(json.dumps({'videos':len(rows),'unique_video_sha256':len({r['video_sha256'] for r in rows}),
                   'risk_counts':dict(Counter(r['risk_annotation'] for r in rows)),
                   'prior_annotations_preserved':True},ensure_ascii=False))

if __name__=='__main__':main()
