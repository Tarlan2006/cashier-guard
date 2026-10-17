import {
  ArrowDownToLine,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Expand,
  ExternalLink,
  FileVideo2,
  Film,
  LoaderCircle,
  Play,
  ScanLine,
  ShieldCheck,
} from "lucide-react";
import { ReviewSummary } from "./ReviewSummary";
import { timecode } from "../api";
import type { ApiError, Frame, Job } from "../api";
import { getEventAssessment, getResultAssessment } from "../assessment";
import { AssessmentBadge, AssessmentIcon } from "./AssessmentBadge";
const stages = [
  { id: "queued", label: "В очереди" },
  { id: "preparing", label: "Подготовка и преобразование" },
  { id: "analyzing", label: "Анализ событий" },
  { id: "matching", label: "Проверка правил" },
];
type Props = {
  job: Job | null;
  phase: string;
  issue: ApiError | null;
  activeEvent: number;
  onSelect: (index: number) => void;
  onSeek: (seconds: number) => void;
  canPlay: boolean;
  onFrame: (frame: Frame) => void;
  onResume: () => void;
  canResume: boolean;
  onReset: () => void;
  hasKey: boolean;
  hideSummary?: boolean;
  onOpenSettings?: () => void;
};
export function ResultPanel({
  job,
  phase,
  issue,
  activeEvent,
  onSelect,
  onSeek,
  canPlay,
  onFrame,
  onResume,
  canResume,
  onReset,
  hasKey,
  hideSummary = false,
  onOpenSettings,
}: Props) {
  const busy = ["uploading", "restoring", "processing"].includes(phase);
  const result = getResultAssessment(phase === "done" && !issue ? job : null);
  const completed = phase === "done" && !issue && result.level !== "incomplete";
  const invalidResult = phase === "done" && !issue && !completed;
  const event = completed ? job?.violations[activeEvent] : undefined;
  const assessment = event ? getEventAssessment(event) : null;
  function download() {
    if (!job) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(job, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `cashier-guard-${job.job_id}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const title =
    phase === "failed"
      ? "Обработка не завершена"
      : issue?.kind === "auth"
        ? "Нужно исправить ключ доступа"
        : issue?.kind === "not_found"
          ? "Проверка не найдена"
          : issue?.kind === "timeout"
            ? "Время ожидания истекло"
            : "Получение результата остановлено";
  return (
    <section className="result-panel" aria-labelledby="result-heading">
      <div className="panel-heading">
        <h2 id="result-heading">Результат проверки</h2>
        {job && ["done", "failed"].includes(phase) ? (
          <button className="text-button" onClick={download}>
            <ArrowDownToLine size={16} />
            Скачать JSON
          </button>
        ) : (
          <span>
            {busy
              ? "В процессе"
              : issue
                ? "Требует внимания"
                : "Ожидание записи"}
          </span>
        )}
      </div>
      <div role="status" aria-live="polite" className="visually-hidden">
        {completed
          ? result.label
          : issue
            ? `Проверка не завершена. ${title}`
            : busy
              ? job?.stage === "preparing"
                ? "Подготовка и преобразование видео в MP4"
                : "Видео обрабатывается"
              : ""}
      </div>
      {phase === "idle" && !issue && (
        <div className="empty-result">
          <div className="empty-visual">
            <Film size={46} strokeWidth={1.15} />
          </div>
          <h3>Всё важное — в одном месте</h3>
          <p>
            Загрузите запись. Здесь появятся события, точное время и кадры для
            проверки.
          </p>
          <div className="result-features">
            <div>
              <Clock3 size={18} />
              Таймкоды с точностью до миллисекунды
            </div>
            <div>
              <FileVideo2 size={18} />
              Кадры с увеличением деталей
            </div>
            <div>
              <ShieldCheck size={18} />
              Объяснение и источник правила
            </div>
          </div>
        </div>
      )}
      {busy && (
        <div className="processing">
          <AssessmentBadge level="incomplete" label="Проверка не завершена" />
          <div className="processing-symbol">
            <ScanLine size={38} strokeWidth={1.4} />
            <span />
          </div>
          <h3>
            {phase === "uploading"
              ? "Загружаем запись"
              : phase === "restoring"
                ? "Восстанавливаем проверку"
                : job?.stage === "preparing"
                  ? "Подготавливаем видео"
                  : "Проверяем видеозапись"}
          </h3>
          <p>
            {job?.stage === "preparing"
              ? "Проверяем файл и преобразуем видео в MP4 для анализа."
              : job?.mode === "demo"
                ? "Тестовый сценарий, без распознавания действий."
                : "Ожидаем подтверждённый результат сервиса."}
          </p>
          <ol className="stages">
            {stages.map((stage, index) => {
              const current = stages.findIndex(
                (item) => item.id === job?.stage,
              );
              const done = index < current;
              const active = index === current;
              return (
                <li
                  key={stage.id}
                  className={done ? "complete" : active ? "current" : ""}
                >
                  <span>
                    {done ? (
                      <Check size={14} />
                    ) : active ? (
                      <LoaderCircle size={14} className="spin" />
                    ) : (
                      index + 1
                    )}
                  </span>
                  {stage.label}
                </li>
              );
            })}
          </ol>
          <small>
            {phase === "uploading"
              ? "Не закрывайте вкладку, пока загружается файл."
              : "После обновления этой вкладки текущая проверка восстановится."}
          </small>
          {job?.deadline_at && (
            <p className="deadline">
              Общий срок: до{" "}
              {new Date(job.deadline_at).toLocaleTimeString("ru-RU")} — включая
              загрузку, очередь и преобразование.
            </p>
          )}
        </div>
      )}
      {!busy && (issue || phase === "failed" || invalidResult) && (
        <div
          className="failed-result assessment-incomplete"
          role="alert"
          data-assessment="incomplete"
        >
          <AssessmentIcon level="incomplete" size={36} />
          <h3>Проверка не завершена</h3>
          {issue && <p className="failure-context">{title}</p>}
          <p>
            {issue?.message ??
              job?.error ??
              "Ответ сервиса некорректен. Результат проверки не определён."}
          </p>
          <p className="failure-truth">
            Вердикт не сформирован. Ошибка обработки не означает отсутствие
            нарушений.
          </p>
          {issue?.kind === "auth" && onOpenSettings && (
            <a
              className="settings-recovery"
              href="#settings"
              onClick={(event) => {
                event.preventDefault();
                onOpenSettings();
              }}
            >
              Открыть настройки
            </a>
          )}
          <div className="recovery-actions">
            {canResume && phase !== "failed" && (
              <button
                className="button primary"
                onClick={onResume}
                disabled={!hasKey}
              >
                {issue?.kind === "auth"
                  ? "Продолжить с этим ключом"
                  : "Обновить статус"}
              </button>
            )}
            <button className="button secondary" onClick={onReset}>
              Новая проверка
            </button>
          </div>
          {job?.error_code && (
            <small className="error-code">Код: {job.error_code}</small>
          )}
        </div>
      )}
      {completed && job && (
        <div className="completed-result">
          {!hideSummary && <ReviewSummary job={job} />}
          <ul
            className="assessment-counts"
            aria-label="Количество событий по уровню"
          >
            <li className="assessment-strong_evidence">
              <AssessmentIcon level="strong_evidence" />
              <span>
                Явные признаки нарушения: <strong>{result.strongCount}</strong>
              </span>
            </li>
            <li className="assessment-needs_review">
              <AssessmentIcon level="needs_review" />
              <span>
                Требует уточнения: <strong>{result.reviewCount}</strong>
              </span>
            </li>
          </ul>
          {job.violations.length > 0 && (
            <>
              <div className="event-list" aria-label="Найденные события">
                {job.violations.map((item, index) => (
                  <button
                    key={index}
                    className={`assessment-${getEventAssessment(item).level} ${index === activeEvent ? "active" : ""}`}
                    data-assessment={getEventAssessment(item).level}
                    onClick={() => onSelect(index)}
                    aria-pressed={index === activeEvent}
                  >
                    <span>{index + 1}</span>
                    <span className="event-list-copy">
                      <strong>{item.type}</strong>
                      <AssessmentBadge {...getEventAssessment(item)} />
                    </span>
                    <time>{timecode(item.timecode_sec)}</time>
                    <ChevronRight size={16} />
                  </button>
                ))}
              </div>
              {event && assessment && (
                <article
                  className={`event-detail assessment-${assessment.level}`}
                  data-assessment={assessment.level}
                >
                  <div className="assessment-explanation">
                    <AssessmentBadge
                      level={assessment.level}
                      label={assessment.label}
                    />
                    <h4>Почему выбран этот уровень</h4>
                    <p>{assessment.reason}</p>
                    {job.mode === "demo" && (
                      <p className="assessment-demo-note">
                        Оценка вымышлена для демонстрации интерфейса.
                      </p>
                    )}
                  </div>
                  <div className="evidence-heading">
                    <h4>Кадры-доказательства</h4>
                    <button
                      className="timecode"
                      onClick={() => onSeek(event.timecode_sec)}
                      disabled={!canPlay}
                      title={
                        !canPlay
                          ? "Для перехода нужен исходный файл с доступным предпросмотром в браузере"
                          : "Перейти к событию в видео"
                      }
                    >
                      <Play size={13} />
                      {timecode(event.timecode_sec)}
                    </button>
                  </div>
                  <div className="evidence-frames">
                    {event.evidence_frames.map((frame, index) => (
                      <figure key={index}>
                        <button
                          className="frame-open"
                          onClick={() => onFrame(frame)}
                          aria-label={`Увеличить кадр ${index + 1}, ${timecode(frame.timestamp_sec)}`}
                        >
                          <img
                            src={`data:image/jpeg;base64,${frame.image_base64}`}
                            alt={`Кадр ${index + 1} на отметке ${timecode(frame.timestamp_sec)}`}
                          />
                          <span>
                            <Expand size={17} />
                            Увеличить
                          </span>
                        </button>
                        <figcaption>
                          <span>Кадр {index + 1}</span>
                          <button
                            onClick={() => onSeek(frame.timestamp_sec)}
                            disabled={!canPlay}
                          >
                            {timecode(frame.timestamp_sec)}
                            <ArrowRight size={13} />
                          </button>
                        </figcaption>
                      </figure>
                    ))}
                  </div>
                  <h4>Что произошло</h4>
                  <p>{event.description}</p>
                  <div className="rule-reference">
                    <ShieldCheck size={19} />
                    <div>
                      <strong>
                        {event.rule?.is_demo
                          ? "Вымышленный источник · только для демонстрации"
                          : (event.rule?.title ?? "Норматив не указан")}
                      </strong>
                      {event.rule?.is_demo && <p>{event.rule.title}</p>}
                      <p>
                        {event.rule
                          ? `${event.rule.document} · ${event.rule.section}`
                          : job.mode === "demo"
                            ? "Тестовый пример не связан с реальным нормативом."
                            : "Источник правила не передан в результате."}
                      </p>
                      {event.rule &&
                        !event.rule.is_demo &&
                        /^https?:\/\//i.test(event.rule.url) && (
                          <a
                            href={event.rule.url}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            Открыть источник
                            <ExternalLink size={14} />
                          </a>
                        )}
                      {event.rule?.is_demo && (
                        <span className="demo-source">
                          {event.rule.url} (не является нормативным источником)
                        </span>
                      )}
                    </div>
                  </div>
                </article>
              )}
            </>
          )}
          {job.verdict === "no_violation" && (
            <div className="no-events">
              <CheckCircle2 size={44} strokeWidth={1.2} />
              <h3>Список событий пуст</h3>
              <p>
                {job.mode === "demo"
                  ? "Так выглядит тестовый результат без событий."
                  : "По доступным правилам признаки нарушений не обнаружены."}
              </p>
            </div>
          )}
          {job.timings_sec && (
            <details className="timings">
              <summary>Время обработки</summary>
              <dl>
                {Object.entries(job.timings_sec).map(([name, seconds]) => (
                  <div key={name}>
                    <dt>
                      {{
                        upload: "Загрузка",
                        queued: "Очередь",
                        queue: "Очередь",
                        preparing: "Подготовка и преобразование",
                        analyzing: "Анализ",
                        matching: "Проверка правил",
                        total: "Всего",
                      }[name] ?? name}
                    </dt>
                    <dd>{seconds.toFixed(2)} с</dd>
                  </div>
                ))}
              </dl>
            </details>
          )}
          {job.expires_at && (
            <p className="retention-note">
              Результат доступен до{" "}
              {new Date(job.expires_at).toLocaleString("ru-RU")}. Сохраните
              JSON, если он нужен дольше.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
