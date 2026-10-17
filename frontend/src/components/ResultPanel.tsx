import {
  AlertCircle,
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
import { timecode } from "../api";
import type { ApiError, Frame, Job } from "../api";
const stages = [
  { id: "queued", label: "В очереди" },
  { id: "preparing", label: "Подготовка видео" },
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
}: Props) {
  const busy = ["uploading", "restoring", "processing"].includes(phase);
  const event = job?.violations[activeEvent];
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
        {phase === "done"
          ? "Проверка завершена"
          : issue
            ? title
            : busy
              ? "Видео обрабатывается"
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
          <div className="processing-symbol">
            <ScanLine size={38} strokeWidth={1.4} />
            <span />
          </div>
          <h3>
            {phase === "uploading"
              ? "Загружаем запись"
              : phase === "restoring"
                ? "Восстанавливаем проверку"
                : "Проверяем видеозапись"}
          </h3>
          <p>
            {job?.mode === "demo"
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
              загрузку и очередь.
            </p>
          )}
        </div>
      )}
      {issue && !busy && (
        <div className="failed-result" role="alert">
          <AlertCircle size={36} />
          <h3>{title}</h3>
          <p>{issue.message}</p>
          {phase === "failed" && (
            <p className="failure-truth">
              Вердикт не сформирован. Ошибка обработки не означает отсутствие
              нарушений.
            </p>
          )}
          <div className="recovery-actions">
            {canResume && phase !== "failed" && (
              <button
                className="button primary"
                onClick={onResume}
                disabled={!hasKey}
              >
                {issue.kind === "auth"
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
      {phase === "done" && job && (
        <div className="completed-result">
          <div
            className={`verdict ${job.verdict === "violation" ? "attention" : "clear"}`}
          >
            {job.verdict === "violation" ? (
              <AlertCircle size={24} />
            ) : (
              <CheckCircle2 size={24} />
            )}
            <div>
              <h3>
                {job.mode === "demo"
                  ? job.verdict === "violation"
                    ? "Демо: пример найденных событий"
                    : "Демо: нарушений не обнаружено"
                  : job.verdict === "violation"
                    ? "Есть признаки возможных нарушений"
                    : "Нарушение не обнаружено"}
              </h3>
              <p>
                {job.mode === "demo"
                  ? "События созданы тестовым сценарием. ML не анализировал содержимое видео."
                  : "Проверьте доказательства и примите решение самостоятельно."}
              </p>
            </div>
          </div>
          {job.violations.length > 0 && (
            <>
              <div className="event-list" aria-label="Найденные события">
                {job.violations.map((item, index) => (
                  <button
                    key={index}
                    className={index === activeEvent ? "active" : ""}
                    onClick={() => onSelect(index)}
                    aria-pressed={index === activeEvent}
                  >
                    <span>{index + 1}</span>
                    <strong>{item.type}</strong>
                    <time>{timecode(item.timecode_sec)}</time>
                    <ChevronRight size={16} />
                  </button>
                ))}
              </div>
              {event && (
                <article className="event-detail">
                  <div className="evidence-heading">
                    <h4>Кадры-доказательства</h4>
                    <button
                      className="timecode"
                      onClick={() => onSeek(event.timecode_sec)}
                      disabled={!canPlay}
                      title={
                        !canPlay
                          ? "Повторно выберите локальный видеофайл для перехода к событию"
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
                          : "Тестовый пример не связан с реальным нормативом."}
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
                        preparing: "Подготовка",
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
