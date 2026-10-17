import { useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Clock3,
  ExternalLink,
  Eye,
  EyeOff,
  FileVideo2,
  Film,
  Info,
  KeyRound,
  LoaderCircle,
  Play,
  RefreshCw,
  ScanLine,
  ShieldCheck,
  TestTubeDiagonal,
  Upload,
  X,
  AlertCircle,
} from "lucide-react";
import { request, timecode } from "./api";
import type { Health, Job } from "./api";

const stages = [
  { id: "queued", label: "В очереди" },
  { id: "preparing", label: "Подготовка" },
  { id: "analyzing", label: "Анализ видео" },
  { id: "matching", label: "Проверка правил" },
];

function initialKey() {
  try {
    return sessionStorage.getItem("cashier-guard-key") ?? "";
  } catch {
    return "";
  }
}

function scrollBehavior(): ScrollBehavior {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ? "auto"
    : "smooth";
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [healthChecked, setHealthChecked] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [videoUrl, setVideoUrl] = useState("");
  const [key, setKey] = useState(initialKey);
  const [showKey, setShowKey] = useState(false);
  const [scenario, setScenario] = useState<"violation" | "no_violation">(
    "violation",
  );
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");
  const [retry, setRetry] = useState(0);
  const [activeEvent, setActiveEvent] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const submittedKey = useRef("");
  const submitLock = useRef(false);
  const busy = uploading || job?.status === "processing";
  const isDemo = (job?.mode ?? health?.mode) === "demo";
  const event = job?.violations[activeEvent];
  const maxMB = health?.max_upload_mb ?? 100;

  async function checkHealth(signal?: AbortSignal) {
    try {
      setHealth(await request<Health>("/health", "", { signal }));
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setHealth(null);
    }
    setHealthChecked(true);
  }

  useEffect(() => {
    const controller = new AbortController();
    void checkHealth(controller.signal);
    const timer = setInterval(
      () => void checkHealth(controller.signal),
      15_000,
    );
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!file) {
      setVideoUrl("");
      return;
    }
    const url = URL.createObjectURL(file);
    setVideoUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    if (!job || job.status !== "processing") return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const id = job.job_id;
    const poll = async () => {
      try {
        const next = await request<Job>(`/jobs/${id}`, submittedKey.current, {
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        setJob(next);
        setPollError("");
        if (next.status === "processing") timer = setTimeout(poll, 1000);
      } catch (error) {
        if (controller.signal.aborted) return;
        setPollError(
          error instanceof Error
            ? error.message
            : "Не удалось получить статус обработки.",
        );
      }
    };
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [job?.job_id, job?.status, retry]);

  function selectFile(next?: File) {
    if (!next || busy) return;
    if (!/\.(mov|mp4)$/i.test(next.name)) {
      setError("Выберите видео в формате MOV или MP4.");
      return;
    }
    if (!next.size) {
      setError("Файл пуст. Выберите другую запись.");
      return;
    }
    if (next.size > maxMB * 1024 * 1024) {
      setError(`Файл слишком большой. Максимум — ${maxMB} МБ.`);
      return;
    }
    setFile(next);
    setJob(null);
    setError("");
    setPollError("");
    setActiveEvent(0);
  }

  async function submit() {
    if (!file || !key.trim() || busy || submitLock.current) return;
    submitLock.current = true;
    setUploading(true);
    setError("");
    setPollError("");
    setJob(null);
    setActiveEvent(0);
    submittedKey.current = key.trim();
    try {
      try {
        sessionStorage.setItem("cashier-guard-key", key.trim());
      } catch {
        /* Private browsing may disable storage. */
      }
      const body = new FormData();
      body.append("file", file);
      body.append("demo_scenario", scenario);
      const response = await request<{ job_id: string; mode: "demo" | "live" }>(
        "/analyze",
        key.trim(),
        {
          method: "POST",
          body,
          signal: AbortSignal.timeout(120_000),
        },
      );
      setJob({
        ...response,
        status: "processing",
        stage: "queued",
        filename: file.name,
        duration_sec: null,
        verdict: null,
        violations: [],
        error: null,
      });
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Не удалось загрузить видео. Проверьте соединение.",
      );
    } finally {
      submitLock.current = false;
      setUploading(false);
    }
  }

  function reset() {
    if (busy) return;
    setFile(null);
    setJob(null);
    setError("");
    setPollError("");
    setActiveEvent(0);
    if (inputRef.current) inputRef.current.value = "";
  }

  function seek(seconds: number) {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = seconds;
    video.scrollIntoView({ behavior: scrollBehavior(), block: "center" });
  }

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

  return (
    <div className="app-shell">
      <a href="#main" className="skip-link">
        Перейти к проверке видео
      </a>
      <aside className="sidebar" aria-label="Навигация">
        <div className="brand">
          <ShieldCheck size={32} strokeWidth={1.65} />
          <span>
            cashier<span className="brand-light">guard</span>
            <small>Контроль кассовых операций</small>
          </span>
        </div>
        <div className="sidebar-rule" />
        <nav>
          <button
            className="nav-item selected"
            onClick={() => document.getElementById("main")?.scrollIntoView()}
            aria-current="page"
          >
            <ScanLine size={19} />
            Проверка видео
            <ChevronRight size={15} />
          </button>
        </nav>
        <div className="sidebar-bottom">
          <button
            className="nav-item help"
            onClick={() => {
              if (detailsRef.current) {
                detailsRef.current.open = true;
                detailsRef.current.scrollIntoView({
                  behavior: scrollBehavior(),
                });
              }
            }}
          >
            <CircleHelp size={18} />
            Как это работает
          </button>
          <div className="sidebar-note">
            <ShieldCheck size={17} />
            <span>
              Решение принимает человек.
              <br />
              Сервис помогает с проверкой.
            </span>
          </div>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            Рабочее пространство <ChevronRight size={14} />
            <span>Проверка видео</span>
          </div>
          <div className={`connection ${health ? "online" : ""}`} role="status">
            <span />
            {health
              ? "Сервис доступен"
              : healthChecked
                ? "Нет соединения"
                : "Подключение…"}
          </div>
        </header>
        <main id="main">
          <div className="page-heading">
            <div>
              <h1>Проверка видео</h1>
              <p>От записи кассы — к событиям, которые стоит проверить.</p>
            </div>
            {(file || job) && (
              <button
                className="button secondary new-check"
                onClick={reset}
                disabled={busy}
              >
                <RefreshCw size={16} />
                Новая проверка
              </button>
            )}
          </div>

          {isDemo && (
            <div className="demo-notice">
              <TestTubeDiagonal size={20} />
              <div>
                <strong>Демонстрационный режим</strong>
                <span>
                  Можно проверить весь сценарий. ML-модули ещё не подключены,
                  результаты тестовые.
                </span>
              </div>
              <span className="demo-label">ДЕМО</span>
            </div>
          )}
          {!health && healthChecked && (
            <div className="alert error" role="alert">
              <AlertCircle size={20} />
              <div>
                Нет связи с сервером. Убедитесь, что backend запущен, и
                повторите подключение.
              </div>
              <button
                className="text-button"
                onClick={() => void checkHealth()}
              >
                Повторить
              </button>
            </div>
          )}

          <div className="workspace">
            <section className="upload-panel" aria-labelledby="upload-heading">
              <div className="panel-heading">
                <h2 id="upload-heading">Видеозапись</h2>
                <span>MOV / MP4</span>
              </div>
              <input
                ref={inputRef}
                id="video-file"
                className="visually-hidden"
                type="file"
                accept=".mov,.mp4,video/quicktime,video/mp4"
                disabled={busy}
                tabIndex={-1}
                onChange={(e) => selectFile(e.target.files?.[0])}
              />
              {!file ? (
                <button
                  type="button"
                  className={`dropzone ${dragging ? "dragging" : ""}`}
                  onClick={() => inputRef.current?.click()}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDragging(false);
                    selectFile(e.dataTransfer.files[0]);
                  }}
                >
                  <div className="upload-symbol">
                    <Upload size={30} strokeWidth={1.5} />
                  </div>
                  <strong>
                    {dragging
                      ? "Отпустите файл здесь"
                      : "Перетащите видео сюда"}
                  </strong>
                  <span>или выберите файл на компьютере</span>
                  <span className="file-pick">
                    Выбрать видео <ArrowRight size={16} />
                  </span>
                  <small>До {maxMB} МБ · длительность до 10 минут</small>
                </button>
              ) : (
                <div className="selected-file">
                  <div className="video-wrap">
                    <video
                      ref={videoRef}
                      src={videoUrl}
                      controls
                      muted
                      playsInline
                      preload="metadata"
                      aria-label="Предпросмотр загруженного видео"
                    />
                  </div>
                  <div className="file-details">
                    <FileVideo2 size={22} />
                    <div>
                      <strong title={file.name}>{file.name}</strong>
                      <span>
                        {(file.size / 1024 / 1024).toFixed(1)} МБ
                        {job?.duration_sec
                          ? ` · ${timecode(job.duration_sec)}`
                          : ""}
                      </span>
                    </div>
                    <button
                      className="icon-button"
                      onClick={reset}
                      disabled={busy}
                      aria-label="Удалить выбранное видео"
                    >
                      <X size={17} />
                    </button>
                  </div>
                  <p className="video-hint">
                    Если браузер не воспроизводит кодек MOV, файл всё равно
                    можно отправить на проверку.
                  </p>
                </div>
              )}

              <div className="key-field">
                <label htmlFor="api-key">
                  <KeyRound size={15} />
                  Ключ доступа к API
                </label>
                <div className="input-wrap">
                  <input
                    id="api-key"
                    type={showKey ? "text" : "password"}
                    value={key}
                    onChange={(e) => setKey(e.target.value)}
                    placeholder="Введите ключ сервиса"
                    autoComplete="off"
                    spellCheck={false}
                    disabled={busy}
                    aria-describedby="key-hint"
                  />
                  <button
                    className="icon-button"
                    aria-label={showKey ? "Скрыть ключ" : "Показать ключ"}
                    type="button"
                    onClick={() => setShowKey(!showKey)}
                  >
                    {showKey ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
                <small id="key-hint">
                  Ключ сохраняется только в этой вкладке.
                </small>
              </div>

              {isDemo && (
                <fieldset className="scenario" disabled={busy}>
                  <legend>Тестовый результат</legend>
                  <div className="segmented">
                    <label className={scenario === "violation" ? "active" : ""}>
                      <input
                        type="radio"
                        name="scenario"
                        value="violation"
                        checked={scenario === "violation"}
                        onChange={() => setScenario("violation")}
                      />
                      С событием
                    </label>
                    <label
                      className={scenario === "no_violation" ? "active" : ""}
                    >
                      <input
                        type="radio"
                        name="scenario"
                        value="no_violation"
                        checked={scenario === "no_violation"}
                        onChange={() => setScenario("no_violation")}
                      />
                      Без событий
                    </label>
                  </div>
                </fieldset>
              )}

              {error && (
                <div className="form-error" role="alert">
                  <AlertCircle size={17} />
                  <span>{error}</span>
                </div>
              )}
              <button
                className="button primary analyze-button"
                onClick={() => void submit()}
                disabled={!file || !key.trim() || !health || busy}
              >
                {busy ? (
                  <LoaderCircle size={18} className="spin" />
                ) : (
                  <ScanLine size={18} />
                )}
                {uploading
                  ? "Загружаем видео…"
                  : busy
                    ? "Проверяем запись…"
                    : isDemo
                      ? "Запустить демопроверку"
                      : "Проверить видео"}
                {!busy && <ArrowRight size={17} />}
              </button>
              <div className="privacy-note">
                <ShieldCheck size={14} />
                <span>
                  Обработка на сервере команды. Без облачных AI-сервисов.
                </span>
              </div>
            </section>

            <section
              className={`result-panel ${job?.status === "done" ? "has-result" : ""}`}
              aria-labelledby="result-heading"
            >
              <div className="panel-heading">
                <h2 id="result-heading">Результат проверки</h2>
                {job?.status === "done" ? (
                  <button className="text-button" onClick={download}>
                    <ArrowDownToLine size={15} />
                    Скачать JSON
                  </button>
                ) : (
                  <span>{busy ? "В процессе" : "Ожидание записи"}</span>
                )}
              </div>
              <div
                aria-live="polite"
                aria-atomic="true"
                className="visually-hidden"
              >
                {job?.status === "done"
                  ? "Проверка завершена"
                  : job?.status === "failed"
                    ? "Обработка не завершена"
                    : busy
                      ? "Видео обрабатывается"
                      : ""}
              </div>

              {!job && !uploading && (
                <div className="empty-result">
                  <div className="empty-visual">
                    <Film size={46} strokeWidth={1.15} />
                    <span className="empty-cross horizontal" />
                    <span className="empty-cross vertical" />
                  </div>
                  <h3>Всё важное — в одном месте</h3>
                  <p>
                    Загрузите запись и запустите проверку.
                    <br />
                    Здесь появятся найденные события и доказательства.
                  </p>
                  <div className="result-features">
                    <div>
                      <Clock3 size={18} />
                      <span>Точное время события</span>
                    </div>
                    <div>
                      <FileVideo2 size={18} />
                      <span>Кадр из вашей записи</span>
                    </div>
                    <div>
                      <ShieldCheck size={18} />
                      <span>Объяснение и правило</span>
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
                    {uploading ? "Загружаем запись" : "Проверяем видеозапись"}
                  </h3>
                  <p>
                    {isDemo
                      ? "Показываем, как будет выглядеть проверка."
                      : "Выделяем события и сопоставляем их с правилами."}
                  </p>
                  <ol className="stages">
                    {stages.map((stage, index) => {
                      const current = stages.findIndex(
                        (s) => s.id === job?.stage,
                      );
                      const done = index < current;
                      const active = !uploading && index === current;
                      return (
                        <li
                          key={stage.id}
                          className={
                            done ? "complete" : active ? "current" : ""
                          }
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
                  <small>Не закрывайте вкладку до окончания проверки.</small>
                </div>
              )}

              {pollError && (
                <div className="alert error" role="alert">
                  <AlertCircle size={19} />
                  <div>
                    {pollError}
                    <button
                      className="text-button"
                      onClick={() => {
                        setPollError("");
                        setRetry(retry + 1);
                      }}
                    >
                      Обновить статус
                    </button>
                  </div>
                </div>
              )}
              {job?.status === "failed" && (
                <div className="failed-result" role="alert">
                  <AlertCircle size={38} />
                  <h3>Не удалось проверить запись</h3>
                  <p>{job.error}</p>
                  <button
                    className="button secondary"
                    onClick={() => void submit()}
                  >
                    Повторить проверку
                  </button>
                </div>
              )}

              {job?.status === "done" && (
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
                            ? "Демо: пример найденного события"
                            : "Демо: нарушений не обнаружено"
                          : job.verdict === "violation"
                            ? "Есть признаки возможных нарушений"
                            : "Нарушение не обнаружено"}
                      </h3>
                      <p>
                        {job.mode === "demo"
                          ? "Тестовый результат. Содержимое видео не анализировалось моделью."
                          : "Результат необходимо проверить человеку."}
                      </p>
                    </div>
                  </div>
                  {job.violations.length > 0 && (
                    <>
                      <div
                        className="event-list"
                        aria-label="Найденные события"
                      >
                        {job.violations.map((item, index) => (
                          <button
                            key={index}
                            className={index === activeEvent ? "active" : ""}
                            onClick={() => setActiveEvent(index)}
                            aria-pressed={index === activeEvent}
                          >
                            <span>{String(index + 1).padStart(2, "0")}</span>
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
                              onClick={() => seek(event.timecode_sec)}
                            >
                              <Play size={12} fill="currentColor" />
                              {timecode(event.timecode_sec)}
                            </button>
                          </div>
                          <div className="evidence-frames">
                            {event.evidence_frames.map((frame, index) => (
                              <figure key={index}>
                                <img
                                  src={`data:image/jpeg;base64,${frame.image_base64}`}
                                  alt={`Кадр из видео на отметке ${timecode(frame.timestamp_sec)}`}
                                />
                                <figcaption>
                                  <span>Кадр {index + 1}</span>
                                  <button
                                    onClick={() => seek(frame.timestamp_sec)}
                                  >
                                    {timecode(frame.timestamp_sec)}{" "}
                                    <ArrowRight size={12} />
                                  </button>
                                </figcaption>
                              </figure>
                            ))}
                          </div>
                          <h4>Что произошло</h4>
                          <p>{event.description}</p>
                          <div className="rule-reference">
                            <ShieldCheck size={18} />
                            <div>
                              <strong>
                                {event.rule?.title ?? "Норматив не указан"}
                              </strong>
                              <p>
                                {event.rule
                                  ? `${event.rule.document} · ${event.rule.section}`
                                  : "Демонстрационный пример не связан с реальным правилом."}
                              </p>
                              {event.rule &&
                                /^https?:\/\//i.test(event.rule.url) && (
                                  <a
                                    href={event.rule.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                  >
                                    Открыть источник <ExternalLink size={13} />
                                  </a>
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
                        {isDemo
                          ? "Так выглядит результат проверки без найденных событий."
                          : "На записи не обнаружены признаки нарушений по доступным правилам."}
                      </p>
                    </div>
                  )}
                </div>
              )}
            </section>
          </div>

          <details className="how-it-works" ref={detailsRef}>
            <summary>
              <Info size={17} />
              Как проходит проверка
              <ChevronRight size={16} />
            </summary>
            <div className="how-grid">
              <div>
                <h3>Загрузите запись</h3>
                <p>
                  Выберите MOV или MP4 и укажите ключ доступа. Видео отправится
                  на сервер команды.
                </p>
              </div>
              <div>
                <h3>Дождитесь результата</h3>
                <p>
                  В рабочем режиме ML1 находит события, а ML2 проверяет их и
                  сопоставляет с каталогом правил.
                </p>
              </div>
              <div>
                <h3>Проверьте доказательства</h3>
                <p>
                  Изучите кадры, таймкоды и источники. Деморежим проверяет
                  интерфейс, а не действия на видео.
                </p>
              </div>
            </div>
          </details>
          <footer>
            <span>Cashier Guard</span>
            <span>Помощь в проверке · окончательное решение за человеком</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
