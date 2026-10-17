import fs from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile, FileBlob } from '@oai/artifact-tool';

const root = fileURLToPath(new URL('../../', import.meta.url));
if (process.argv.includes('--preview-existing') || process.argv.includes('--update-events')) {
  const target = `${root}/outputs/ForteBank_реестр_и_разметка.xlsx`;
  const existing = await SpreadsheetFile.importXlsx(await FileBlob.load(target));
  if (process.argv.includes('--preview-existing')) {
    const preview = await existing.render({sheetName:'События',range:'A1:K8',scale:1,format:'png'});
    await fs.writeFile(`${root}/work/forte-table/events-notes-before.png`,new Uint8Array(await preview.arrayBuffer()));
    console.log('Existing notes rendered.');
    process.exit(0);
  }
  await fs.copyFile(target,`${root}/work/forte-table/before-multiple-events.xlsx`,fs.constants.COPYFILE_EXCL);
  const manifestPath = `${root}/outputs/forte_dataset_manifest.json`;
  await fs.copyFile(manifestPath,`${root}/work/forte-table/before-multiple-events.json`,fs.constants.COPYFILE_EXCL);
  existing.worksheets.getItem('Реестр').getRange('A9').values=[['Х-4/Х-47: один видеоряд, отметки 57 и 68 с. Х-5/Х-48: копии без отметок. Копии одной группы — в одной выборке.']];
  const events = existing.worksheets.getItem('События');
  events.getRange('A4').values=[['Сохранены 22 положительные отметки источника. В одном видео возможно несколько нарушений. Каждое событие — отдельная строка.']];
  events.getRange('A5').values=[['X-4 и X-47: сохранить обе отметки, 57 и 68 с. При просмотре определить: отдельные события или один продолжающийся эпизод.']];
  existing.recalculate();
  const checks = await existing.inspect({kind:'table',range:'События!A4:A5',include:'values',tableMaxRows:2,tableMaxCols:1,maxChars:1800});
  console.log(checks.ndjson);
  const errors = await existing.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},maxChars:1000});
  console.log(errors.ndjson);
  for (const [sheetName,range,name] of [['События','A1:K8','events-notes-after'],['Реестр','A9:N10','registry-notes-after']]) {
    const preview = await existing.render({sheetName,range,scale:1,format:'png'});
    await fs.writeFile(`${root}/work/forte-table/${name}.png`,new Uint8Array(await preview.arrayBuffer()));
  }
  await (await SpreadsheetFile.exportXlsx(existing)).save(target);
  const manifest = JSON.parse(await fs.readFile(manifestPath,'utf8'));
  const groups = new Map();
  for (const video of manifest.videos) {
    if (!groups.has(video.sha256)) groups.set(video.sha256,[]);
    groups.get(video.sha256).push(video);
  }
  manifest.annotation_policy = {
    unit:'source_annotation',
    multiple_events_per_video_allowed:true,
    preserve_all_source_annotations:true,
    distinct_timecodes_do_not_confirm_distinct_events:true,
    split_group_key:'sha256',
    review_scope:'full_video',
    note:'Разные отметки одного видеоряда могут указывать на несколько нарушений или на один продолжающийся эпизод. Исходные отметки не удаляются; число событий определяется при ручном просмотре.'
  };
  manifest.content_groups = [...groups.values()].map(videos => ({
    content_group:videos[0].content_group,
    sha256:videos[0].sha256,
    files:videos.map(v => v.filename),
    annotations:videos.map(v => ({source_video_id:v.id,source_file:v.filename,label:v.label,timestamp_raw:v.timestamp_raw,timecode_sec:v.timestamp_sec})),
    annotated_timecodes_sec:[...new Set(videos.map(v => v.timestamp_sec).filter(v => v !== null))].sort((a,b)=>a-b),
    confirmed_event_count:null,
    review_status:'not_reviewed'
  }));
  await fs.writeFile(manifestPath,JSON.stringify(manifest,null,2));
  console.log('Updated notes and grouped annotations. Source rows preserved.');
  process.exit(0);
}
const audit = JSON.parse(await fs.readFile(`${root}/work/forte-data-audit.json`, 'utf8'));
const wb = Workbook.create();
const registry = wb.worksheets.add('Реестр');
const events = wb.worksheets.add('События');
const rules = wb.worksheets.add('Правила');
const raw = wb.worksheets.add('Исходные метки');
const burgundy = '#8B1748', ink = '#202838', amber = '#FFF3D6', muted = '#586577';

function setup(sheet, lastCol, lastRow, title) {
  sheet.showGridLines = false;
  const range = sheet.getRange(`A1:${lastCol}${lastRow}`);
  range.format.font = { name: 'Arial', size: 11, color: ink };
  range.format.verticalAlignment = 'center';
  range.format.rowHeight = 26;
  sheet.getRange('A2').values = [[title]];
  sheet.getRange('A2').format.font = { name: 'Arial', size: 16, bold: true, color: burgundy };
  sheet.getRange('A2').format.rowHeight = 32;
  sheet.getRange(`A3:${lastCol}3`).format.borders = { bottom: { style:'thin', color: burgundy } };
}
function header(sheet, address, vals) {
  const r = sheet.getRange(address);
  r.values = [vals];
  r.format = { fill: burgundy, font: { name:'Arial', size:11, bold:true, color:'#FFFFFF' },
    horizontalAlignment:'center', verticalAlignment:'center', wrapText:true, rowHeight:48 };
}
function columns(sheet, widths, lastRow) {
  widths.forEach((w, i) => sheet.getRangeByIndexes(0,i,lastRow,1).format.columnWidth=w);
}
function context(sheet, row, text) {
  sheet.getRange(`A${row}`).values=[[text]];
  sheet.getRange(`A${row}`).format.font={name:'Arial',size:11,color:muted};
}

setup(registry,'N',53,'ForteBank: реестр датасета');
columns(registry,[12,18,21,23,14,15,13,13,18,15,11,54,22,22],53);
registry.tabColor=burgundy;
registry.getRange('A5:B7').values=[['Видеофайлов',null],['Нарушение',null],['Без нарушения',null]];
registry.getRange('B5:B7').formulas=[['=COUNTA(A12:A53)'],['=COUNTIFS(C12:C53,"нарушение")'],['=COUNTIFS(C12:C53,"без нарушения")']];
registry.getRange('D5:E7').values=[['Уникальных записей',audit.summary.unique_video_bytes],['Общий хронометраж, мин',null],['Объём, МиБ',null]];
registry.getRange('E6:E7').formulas=[['=SUM(F12:F53)/60'],['=SUM(G12:G53)']];
registry.getRange('E6:E7').setNumberFormat('0.0');
context(registry,9,'Дубли: Х-4/Х-47 (57 и 68 с) и Х-5/Х-48. Копии одной группы оставлять в одной выборке.');
context(registry,10,'ID нормализован к латинской X. Файлы не переименованы. Жёлтые столбцы заполняются вручную.');
const regHeaders=['ID видео','Файл','Метка источника','Исходный таймкод','Таймкод, с','Длительность, с','Размер, МиБ','Средний FPS','Размер кадра','Группа дублей','Копий','Замечание аудита','Выборка','Просмотр'];
header(registry,'A11:N11',regHeaders);
registry.getRange('A12:N53').values=audit.records.map(r=>{
  const v=r.metadata.video_tracks[0];
  return [r.id,r.filename,r.label,r.timestamp_raw,r.timestamp_sec,r.metadata.duration_sec,r.bytes/2**20,v.average_fps,`${v.width} × ${v.height}`,r.content_group,r.copies,r.flags.join('; '),null,'Не просмотрено'];
});
registry.getRange('E12:H53').setNumberFormat('0.00');
registry.getRange('L12:L53').format.wrapText=true;
registry.getRange('M12:N53').format.fill=amber;
registry.getRange('M12:M53').dataValidation={rule:{type:'list',values:['Разработка','Проверка','Отложено']}};
registry.getRange('N12:N53').dataValidation={rule:{type:'list',values:['Не просмотрено','Просмотрено','Нужен повтор']}};
registry.getRange('K12:K53').conditionalFormats.add('cellIs',{operator:'greaterThan',formula:1,format:{fill:'#FDE8EA',font:{color:'#9F2340',bold:true}}});
for(let i=0;i<audit.records.length;i++) if(audit.records[i].flags.length)registry.getRange(`A${i+12}:N${i+12}`).format.rowHeight=60;
registry.tables.add('A11:N53',true,'VideoRegistry');
registry.freezePanes.freezeRows(11);
registry.freezePanes.freezeColumns(2);

setup(events,'K',32,'Ручная разметка событий');
columns(events,[14,12,19,17,17,48,40,30,36,17,29],32);
events.tabColor='#B65A80';
context(events,4,'Начните с 22 положительных отметок. Для дополнительных событий добавляйте отдельные строки.');
context(events,5,'X-4 и X-47: один видеоряд, две отметки источника. Проверить обе; считать двумя событиями пока нельзя.');
context(events,6,'Записывайте только видимые действия. Невидимые обстоятельства и спорные выводы вынесите в ограничения.');
context(events,7,'Содержимое видео, кадры и их описания хранить локально; не передавать облачным AI-сервисам.');
context(events,8,'Для отрицательных роликов сначала отмечайте просмотр в реестре. Дополнительные события добавляйте по необходимости.');
header(events,'A10:K10',['ID записи','ID видео','Файл','Отметка источника, с','Уточнённое время, с','Что видно на видео','Что не видно / неоднозначно','Предполагаемый тип','Кадр-доказательство','ID правила','Следующее действие']);
const positive=audit.records.filter(r=>r.label==='нарушение');
events.getRange('A11:K32').values=positive.map((r,i)=>[`OBS-${String(i+1).padStart(3,'0')}`,r.id,r.filename,r.timestamp_sec,null,null,null,null,null,null,null]);
events.getRange('E11:J32').format.fill=amber;
events.getRange('D11:E32').setNumberFormat('0.00');
events.getRange('F11:I32').format.wrapText=true;
events.getRange('K11:K32').formulas=positive.map((r,i)=>{const n=i+11;return [`=IF(F${n}="","Описать действие",IF(E${n}="","Уточнить время",IF(H${n}="","Указать тип",IF(I${n}="","Добавить кадр",IF(J${n}="","Подобрать правило","Проверить правило вручную")))))`];});
events.getRange('A11:K32').format.rowHeight=48;
events.tables.add('A10:K32',true,'EventReview');
events.freezePanes.freezeRows(10);
events.freezePanes.freezeColumns(3);

setup(rules,'J',22,'Каталог проверяемых правил');
columns(rules,[15,29,43,43,40,24,43,43,19,25],22);
rules.tabColor='#B65A80';
context(rules,4,'Пока правила не исследованы: шаблон оставлен пустым. Заполняйте после ручного просмотра примеров.');
context(rules,5,'Используйте применимые открытые источники РК. Проверяйте актуальность документа, пункт и условия применения.');
context(rules,6,'Вывод по видео — признак возможного нарушения для проверки человеком. Связь с источником должна быть обоснована.');
context(rules,7,'Обязательное действие нельзя считать пропущенным без просмотра всей относящейся к нему последовательности.');
header(rules,'A10:J10',['ID правила','Тип события','Визуальные признаки','Документ','Ссылка','Пункт / раздел','Условия применения','Когда вывод невозможен','Дата проверки','Статус проверки']);
rules.getRange('A11:J22').values=Array.from({length:12},()=>Array(10).fill(null));
rules.getRange('A11:J22').format.fill=amber;
rules.getRange('A11:J22').format.rowHeight=48;
rules.getRange('B11:H22').format.wrapText=true;
rules.getRange('I11:I22').setNumberFormat('dd.mm.yyyy');
rules.getRange('J11:J22').dataValidation={rule:{type:'list',values:['Черновик','Проверяется','Проверено','Отклонено']}};
rules.tables.add('A10:J22',true,'RuleCatalog');
rules.freezePanes.freezeRows(10);
rules.freezePanes.freezeColumns(2);

setup(raw,'C',49,'Разметка организаторов');
columns(raw,[27,27,32],49);
context(raw,4,'Источник: open.zip / open/open_labels.xlsx, лист labels. Исходные значения сохранены без исправлений.');
context(raw,5,'Пустая отметка времени у отрицательного видео означает отсутствие отметки, а не нулевую секунду.');
context(raw,6,'Ограничения работы: Кейс_ForteBank.pdf, разделы 4–7 и FAQ. Видео и кадры в книгу не включены.');
header(raw,'A7:C7',audit.raw_labels[0]);
raw.getRange('A8:C49').values=audit.raw_labels.slice(1);
raw.tables.add('A7:C49',true,'OriginalLabels');
raw.freezePanes.freezeRows(7);

wb.recalculate();
const summary=await wb.inspect({kind:'table',range:'Реестр!A5:E7',include:'values,formulas',tableMaxRows:3,tableMaxCols:5,maxChars:1800});
console.log(summary.ndjson);
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},maxChars:1000});
console.log(errors.ndjson);
// Check that a partially filled event still asks for the missing prerequisite.
events.getRange('F11').values=[['Временная проверка формулы']];
wb.recalculate();
if(events.getRange('K11').values[0][0]!=='Уточнить время')throw new Error('Workflow prerequisite check failed');
events.getRange('F11').values=[[null]];
wb.recalculate();
for(const [sheetName,range,file] of [
 ['Реестр','A1:H17','registry-left'],['Реестр','I11:N17','registry-right'],
 ['События','A1:F14','events-left'],['События','G10:K14','events-right'],
 ['Правила','A1:E13','rules-left'],['Правила','F10:J13','rules-right'],
 ['Исходные метки','A1:C16','source']]) {
 const blob=await wb.render({sheetName,range,scale:1.5,format:'png'});
 await fs.writeFile(`${root}/work/forte-table/${file}.png`,new Uint8Array(await blob.arrayBuffer()));
}
const output=await SpreadsheetFile.exportXlsx(wb);
await output.save(`${root}/outputs/ForteBank_реестр_и_разметка.xlsx`);
const manifest={schema_version:1,source_archive:'open.zip',inspection:'metadata_only',summary:audit.summary,
 videos:audit.records.map(({path,...r})=>({...r,relative_path:`videos/${r.filename}`}))};
await fs.writeFile(`${root}/outputs/forte_dataset_manifest.json`,JSON.stringify(manifest,null,2));
console.log('Workbook and metadata manifest exported. Video content was not decoded.');
