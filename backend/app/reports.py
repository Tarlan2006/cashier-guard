"""On-demand private reports. Snapshot data only; no inference or external fetching."""
import base64
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, HRFlowable

from .models import JobResponse

FONT_DIR = Path(__file__).with_name('fonts')
for name, filename in [('CG', 'DejaVuSans.ttf'), ('CGBold', 'DejaVuSans-Bold.ttf')]:
    pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / filename)))
pdfmetrics.registerFontFamily('CG', normal='CG', bold='CGBold', italic='CG', boldItalic='CGBold')
DECISIONS = {'unreviewed':'Не рассмотрено', 'confirmed':'Подтверждено человеком', 'rejected':'Отклонено человеком'}
STATUS = {'processing':'В процессе', 'done':'Завершено', 'failed':'Ошибка', 'cancelled':'Отменено'}


def display_time(value):
    if not value: return 'Не указана'
    try: return datetime.fromisoformat(value).astimezone(timezone.utc).strftime('%d.%m.%Y %H:%M:%S UTC')
    except ValueError: return str(value)


def timecode(value):
    millis=round(value*1000)
    return f'{millis//60000:02}:{millis//1000%60:02}.{millis%1000:03}'


def build_report(job: JobResponse) -> bytes:
    output=BytesIO()
    doc=SimpleDocTemplate(output,pagesize=A4,rightMargin=42,leftMargin=42,topMargin=54,bottomMargin=48,
                          title='Cashier Guard - Отчёт по проверке',author='Cashier Guard')
    styles={
        'body':ParagraphStyle('body',fontName='CG',fontSize=9,leading=14,spaceAfter=7,splitLongWords=True),
        'title':ParagraphStyle('title',fontName='CGBold',fontSize=21,leading=27,spaceAfter=14),
        'h2':ParagraphStyle('h2',fontName='CGBold',fontSize=13,leading=19,spaceBefore=14,spaceAfter=8,keepWithNext=True),
        'meta':ParagraphStyle('meta',fontName='CG',fontSize=8,leading=12,spaceAfter=7,textColor=colors.HexColor('#475569'),splitLongWords=True),
        'caption':ParagraphStyle('caption',fontName='CG',fontSize=8,leading=12,spaceAfter=7,textColor=colors.HexColor('#475569'),keepWithNext=True),
    }
    story=[]
    def text(value,kind='body'):
        # All model/reviewer copy is text, never ReportLab markup.
        safe=escape(str(value)).replace('\n','<br/>')
        story.append(Paragraph(safe,styles[kind]))
    def pair(name,value): text(f'{name}: {value}')
    text('Отчёт по проверке','title')
    text('Cashier Guard | Сформирован '+display_time(datetime.now(timezone.utc).isoformat()),'meta')
    pair('Видео',job.filename)
    pair('Дата загрузки',display_time(job.created_at))
    pair('Дата завершения',display_time(job.completed_at))
    pair('Метки',', '.join(job.tags) or 'Нет')
    pair('Статус',STATUS[job.status])
    pair('Полнота анализа','Завершён по контракту сервиса; полнота распознавания не гарантируется' if job.status=='done' else 'Анализ не завершён. Итогового заключения нет')
    if job.error: pair('Сообщение сервиса',job.error)
    if job.mode=='demo':
        text('ДЕМОНСТРАЦИОННАЯ ЗАПИСЬ. События заданы тестовым сценарием. Это не результат анализа содержимого видео.','h2')
    text('Найденное моделью событие - предположение для проверки. Только явное сохранённое решение человека означает подтверждение проверяющим. Оно не заменяет юридическое заключение.')
    pair('Видеоархив','Доступен на сервере на момент формирования отчёта' if job.video_available else 'Недоступен: срок истёк, файл отсутствует или не был сохранён')
    if job.video_expires_at: pair('Срок хранения видео',display_time(job.video_expires_at))
    pair('Срок хранения результата, кадров и решений',display_time(job.expires_at))
    text('Обнаруженные события','h2')
    if not job.violations:
        text('Сервис не вернул обнаруженных событий.' if job.status=='done' else 'Список событий отсутствует: анализ не завершён. Это не подтверждает отсутствие нарушений.')
    for n,event in enumerate(job.violations,1):
        story.append(HRFlowable(width='100%',thickness=.5,color=colors.HexColor('#e2e8f0'),spaceBefore=8,spaceAfter=4))
        text(f'{n}. {event.type} | {timecode(event.timecode_sec)}','h2')
        pair('Предположение модели',event.description)
        pair('Оценка модели','Явные признаки по оценке модели' if event.assessment=='strong_evidence' else 'Требует уточнения')
        pair('Объяснение оценки',event.assessment_reason or 'Отдельное объяснение оценки не предоставлено сервисом')
        review=event.human_review
        pair('Решение человека',DECISIONS[review.decision] if review else 'Не рассмотрено')
        pair('Комментарий проверяющего',review.comment if review and review.comment else 'Не указан')
        pair('Время изменения решения',display_time(review.updated_at if review else None))
        if job.mode=='demo': text('Решения по этой демонстрационной записи не подтверждают реальное нарушение.','meta')
        rule=event.rule
        if rule and not rule.is_demo and not rule.id.startswith('demo:'):
            pair('Правило из сохранённого ответа',rule.title)
            pair('Документ',rule.document)
            pair('Раздел',rule.section)
            url=escape(rule.url,{'"':'&quot;'})
            story.append(Paragraph(f'<link href="{url}" color="#9f1239">{escape(rule.url)}</link>',styles['body']))
            text('Ссылка сохранена в результате сервиса. Её актуальная доступность при формировании PDF не проверялась.','meta')
        else:
            text('Источник правила недоступен: реальное правило не предоставлено или источник является демонстрационным.')
        if not event.evidence_frames: text('Кадры события недоступны.')
        for i,frame in enumerate(event.evidence_frames,1):
            try:
                raw=base64.b64decode(frame.image_base64,validate=True)
                with PILImage.open(BytesIO(raw)) as image:
                    image.load();w,h=image.size
                scale=min(1,doc.width/w,210/h)
                text(f'Кадр {i} | {timecode(frame.timestamp_sec)}','caption')
                story.append(Image(BytesIO(raw),width=w*scale,height=h*scale,hAlign='LEFT'))
                story.append(Spacer(1,10))
            except (ValueError,OSError): text(f'Кадр {i} недоступен: сохранённое изображение не удалось прочитать.')
    def page(canvas,document):
        canvas.saveState();canvas.setFont('CG',8);canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.drawString(42,A4[1]-29,'Cashier Guard | Отчёт по сохранённой проверке')
        canvas.drawString(42,25,'Оценка модели и решение человека указаны раздельно')
        canvas.drawRightString(A4[0]-42,25,f'Страница {document.page}')
        canvas.restoreState()
    doc.build(story,onFirstPage=page,onLaterPages=page)
    return output.getvalue()
