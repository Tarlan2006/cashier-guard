import fs from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import crypto from 'node:crypto';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const root=fileURLToPath(new URL('../../', import.meta.url));
const data=JSON.parse(await fs.readFile(`${root}/work/legal/rules-data.json`,'utf8'));
const pdf=await fs.readFile(`${root}/work/legal/nbk-231-current.pdf`);
data.sources[0].sha256=crypto.createHash('sha256').update(pdf).digest('hex');
const wb=Workbook.create();
const rules=wb.worksheets.add('Правила');
const limits=wb.worksheets.add('Границы проверки');
const burgundy='#8B1748',ink='#202838',muted='#586577';
function setup(sheet,widths,lastRow,title){
  sheet.showGridLines=false;
  sheet.getRangeByIndexes(0,0,lastRow,widths.length).format.font={name:'Arial',size:11,color:ink};
  sheet.getRangeByIndexes(0,0,lastRow,widths.length).format.verticalAlignment='top';
  widths.forEach((w,i)=>sheet.getRangeByIndexes(0,i,lastRow,1).format.columnWidth=w);
  sheet.getRange('A2').values=[[title]];
  sheet.getRange('A2').format.font={name:'Arial',size:16,bold:true,color:burgundy};
  sheet.getRange('A2').format.rowHeight=32;
  sheet.tabColor=burgundy;
}
function note(sheet,address,text,height=30){
  const range=sheet.getRange(address);range.merge();range.values=[[text]];
  range.format={wrapText:true,rowHeight:height,font:{name:'Arial',size:11,color:muted},verticalAlignment:'center'};
}
function header(sheet,address,text){
  sheet.getRange(address).values=[text];
  sheet.getRange(address).format={fill:burgundy,font:{name:'Arial',size:11,color:'#FFFFFF',bold:true},wrapText:true,rowHeight:42,verticalAlignment:'center'};
}
setup(rules,[17,36,30,56,65,62,48,26],18,'ForteBank: нормативные правила для разметки');
note(rules,'A4:H4','Источник: постановление Правления НБРК от 29.11.2019 № 231, регистрация № 19680. Проверены конкретные пункты Правил.',30);
note(rules,'A5:H5','Текст ЭКБ скачан 17.10.2026. Дата редакции на титуле PDF — 16.03.2026. Наличие этих типов событий в датасете пока не проверено.',30);
note(rules,'A6:H6',data.sources[0].official_url,26);
note(rules,'A7:H7','Порядок проверки: вид операции → вся последовательность → условия нормы → исключения → таймкод и кадры. Не делать вывод по отсутствию действия в одном кадре.',30);
note(rules,'A8:H8','Видео и описания обрабатываются локально. Одно видео может иметь несколько событий. Все исходные отметки сохраняются. Жёлтый столбец заполняется после ручного просмотра.',30);
header(rules,'A10:H10',['ID правила','Тип возможного нарушения','Пункт и страница PDF','Наблюдаемый признак','Условия применения','Когда вывод невозможен','Таймкод и доказательства','Проверка на датасете']);
rules.getRange('A11:H18').values=data.rules.map(r=>[
 r.id,r.type,`${r.paragraph}\nPDF: ${r.pdf_pages.join(', ')}`,
 r.visual_candidate,
 `${r.operation}\n\n${r.required_context.map((s,i)=>`${i+1}. ${s}`).join('\n')}`,
 r.do_not_flag_if.map((s,i)=>`${i+1}. ${s}`).join('\n'),
 `${r.timecode_policy}\n\n${r.evidence_plan}`,
 'Не проверено'
]);
rules.getRange('A11:H18').format.wrapText=true;
rules.getRange('A11:H18').format.rowHeight=128;
rules.getRange('H11:H18').format.fill='#FFF3D6';
rules.getRange('H11:H18').dataValidation={rule:{type:'list',values:['Не проверено','Есть пример','Нужен повтор','Нет примера']}};
rules.tables.add('A10:H18',true,'LegalRuleCatalog');
rules.getRange('A11:H18').format.wrapText=true;
rules.freezePanes.freezeRows(10);rules.freezePanes.freezeColumns(2);

setup(limits,[40,48,105],24,'Что нельзя определять по одному видеоряду');
note(limits,'A4:C4','Ссылки ниже относятся к тому же постановлению НБРК № 231. Источник и версия указаны на листе «Правила».',30);
note(limits,'A5:C5','Эти ограничения предотвращают ложные срабатывания. Неподтверждённая гипотеза не становится доказанным нарушением.',30);
header(limits,'A7:C7',['Ситуация','Нормативная связь','Почему камера не даёт достаточного основания']);
limits.getRange('A8:C14').values=data.restricted_checks.map(r=>[r.topic,r.paragraph,r.reason]);
limits.getRange('A8:C14').format.wrapText=true;
limits.getRange('A8:C14').format.rowHeight=92;
limits.tables.add('A7:C14',true,'VideoLimitations');
limits.freezePanes.freezeRows(7);
note(limits,'A17:C17','Как заполнять разметку',26);
for(let i=0;i<data.review_workflow.length;i++)note(limits,`A${18+i}:C${18+i}`,`${i+1}. ${data.review_workflow[i]}`,42);

wb.recalculate();
const scan=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},maxChars:1200});
console.log(scan.ndjson);
const check=await wb.inspect({kind:'table',range:'Правила!A11:C18',include:'values',tableMaxRows:8,tableMaxCols:3,maxChars:3500});
console.log(check.ndjson);
for(const [sheetName,range,file] of [
 ['Правила','A2:D8','rules-context'],['Правила','A10:D14','rules-left'],['Правила','E10:H14','rules-right'],
 ['Правила','A15:D18','rules-left-end'],['Правила','E15:H18','rules-right-end'],
 ['Границы проверки','A1:C11','limits-top'],['Границы проверки','A12:C23','limits-bottom']]){
 const render=await wb.render({sheetName,range,scale:1,format:'png'});
 await fs.writeFile(`${root}/work/legal/${file}.png`,new Uint8Array(await render.arrayBuffer()));
}
await (await SpreadsheetFile.exportXlsx(wb)).save(`${root}/outputs/ForteBank_правила_РК.xlsx`);
await fs.writeFile(`${root}/outputs/forte_rules_kz.json`,JSON.stringify(data,null,2));
await fs.writeFile(`${root}/outputs/${data.sources[0].local_pdf}`,pdf);
const inspect=`${root}/outputs/ForteBank_правила_РК.xlsx.inspect.ndjson`;
try{await fs.rename(inspect,`${root}/work/legal/export-inspection.ndjson`);}catch(e){if(e.code!=='ENOENT')throw e;}
console.log('Exported 8 candidate rules, 7 limitations, JSON catalog and official source PDF. No dataset content processed.');
