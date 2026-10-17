import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  ChevronRight,
  CircleHelp,
  Eye,
  EyeOff,
  FileVideo2,
  Info,
  KeyRound,
  LoaderCircle,
  RefreshCw,
  ScanLine,
  ShieldCheck,
  TestTubeDiagonal,
  Upload,
} from "lucide-react";
import { scrollBehavior } from "./api";
import type { Frame } from "./api";
import { readKey, useReview } from "./hooks/useReview";
import { useServiceStatus } from "./hooks/useServiceStatus";
import { DEMO_SCENARIOS } from "./demo";
import { FrameDialog } from "./components/FrameDialog";
import { ResultPanel } from "./components/ResultPanel";
import { VideoReview } from "./components/VideoReview";
import type { VideoHandle } from "./components/VideoReview";

export default function App() {
  const [key, setKey] = useState(readKey);
  const [showKey, setShowKey] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [scenario, setScenario] = useState("violation");
  const [dragging, setDragging] = useState(false);
  const [fileError, setFileError] = useState("");
  const [activeEvent, setActiveEvent] = useState(0);
  const [frame, setFrame] = useState<Frame | null>(null);
  const review = useReview(key);
  const service = useServiceStatus();
  const input = useRef<HTMLInputElement>(null);
  const keyInput = useRef<HTMLInputElement>(null);
  const details = useRef<HTMLDetailsElement>(null);
  const preview = useRef<VideoHandle>(null);
  const reattaching = useRef(false);
  const maxMB = service.health?.max_upload_mb ?? 100;
  const isDemo = (review.job?.mode ?? service.health?.mode) === "demo";
  const backendIsDemo = service.health?.mode === "demo";

  useEffect(() => {
    setActiveEvent(0);
    setFrame(null);
  }, [review.job?.job_id]);
  useEffect(() => {
    if (review.issue?.kind === "auth") keyInput.current?.focus();
  }, [review.issue]);

  function reset() {
    review.reset();
    setFile(null);
    setFileError("");
    setActiveEvent(0);
    setFrame(null);
    if (input.current) input.current.value = "";
  }
  function selectFile(next?: File, attach = false) {
    if (!next || review.busy) return;
    if (!/\.(mov|mp4)$/i.test(next.name)) {
      setFileError("Выберите видео в формате MOV или MP4.");
      return;
    }
    if (!next.size) {
      setFileError("Файл пуст. Выберите другую запись.");
      return;
    }
    if (next.size > maxMB * 1024 * 1024) {
      setFileError(`Максимальный размер — ${maxMB} МБ.`);
      return;
    }
    if (
      attach &&
      review.job &&
      (next.name !== review.job.filename ||
        (review.job.size_bytes && next.size !== review.job.size_bytes))
    ) {
      setFileError(
        `Для просмотра выберите исходный файл «${review.job.filename}» с тем же размером. Другой файл можно отправить через «Новая проверка».`,
      );
      return;
    }
    if (!attach) {
      review.reset();
      setActiveEvent(0);
    }
    setFile(next);
    setFileError("");
  }
  function pick(attach = false) {
    reattaching.current = attach;
    input.current?.click();
  }
  function chooseEvent(index: number) {
    setActiveEvent(index);
    const event = review.job?.violations[index];
    if (event) preview.current?.seek(event.timecode_sec);
  }
  const hasTask =
    !!file || !!review.restoredId || !!review.job || !!review.issue;
  const canSubmit =
    !!file &&
    !!key.trim() &&
    !!service.health &&
    service.readiness?.ready === true &&
    !review.busy;
  const checkNames: Record<string, string> = {
    ffmpeg: "FFmpeg",
    rules: "Каталог правил",
    ml1: "ML1",
    ml2: "ML2",
  };

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
            onClick={() =>
              document
                .getElementById("main")
                ?.scrollIntoView({ behavior: scrollBehavior() })
            }
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
              if (details.current) {
                details.current.open = true;
                details.current.scrollIntoView({ behavior: scrollBehavior() });
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
            Рабочее пространство
            <ChevronRight size={14} />
            <span>Проверка видео</span>
          </div>
          <div
            className={`connection ${service.health ? "online" : ""}`}
            role="status"
          >
            <span />
            {service.health
              ? "Backend доступен"
              : service.checked
                ? "Нет соединения"
                : "Подключение…"}
          </div>
        </header>
        <main id="main">
          <div className="page-heading">
            <div>
              <h1>Проверка видео</h1>
              <p>
                События, точное время и кадры для проверки кассовых операций.
              </p>
            </div>
            {hasTask && (
              <button
                className="button secondary new-check"
                onClick={reset}
                disabled={review.busy}
              >
                <RefreshCw size={17} />
                Новая проверка
              </button>
            )}
          </div>
          {isDemo && (
            <div className="demo-notice">
              <TestTubeDiagonal size={21} />
              <div>
                <strong>Демонстрационный режим</strong>
                <span>
                  События и источники вымышлены. Используйте синтетическое
                  видео: модели ещё не подключены.
                </span>
              </div>
              <span className="demo-label">ДЕМО</span>
            </div>
          )}
          {service.checked &&
            (!service.health || !service.readiness?.ready) && (
              <div className="alert error readiness-alert" role="alert">
                <AlertCircle size={20} />
                <div>
                  <strong>
                    {!service.health
                      ? "Сервер недоступен"
                      : "Обработка пока недоступна"}
                  </strong>
                  <p>
                    {!service.health
                      ? "Проверьте подключение и запуск backend. Сохранённая проверка не потеряна."
                      : !service.readiness
                        ? "Не удалось проверить компоненты обработки."
                        : "Проверьте перечисленные компоненты перед новой загрузкой."}
                  </p>
                  {service.readiness && (
                    <ul>
                      {Object.entries(service.readiness.checks)
                        .filter(([, check]) => !check.ready)
                        .map(([name, check]) => (
                          <li key={name}>
                            {checkNames[name] ?? name}: {check.detail}
                          </li>
                        ))}
                    </ul>
                  )}
                </div>
                <button className="text-button" onClick={service.refresh}>
                  Повторить
                </button>
              </div>
            )}

          <div className="workspace">
            <section className="upload-panel" aria-labelledby="upload-heading">
              <div className="panel-heading">
                <h2 id="upload-heading">Видеозапись</h2>
                <span>MOV / MP4 · до {maxMB} МБ</span>
              </div>
              <div className="form-actions">
                <button
                  className="button primary analyze-button"
                  onClick={() => {
                    if (file) {
                      setFileError("");
                      void review.submit(file, scenario);
                    }
                  }}
                  disabled={!canSubmit}
                >
                  {review.busy ? (
                    <LoaderCircle size={19} className="spin" />
                  ) : (
                    <ScanLine size={19} />
                  )}
                  {review.phase === "uploading"
                    ? "Загружаем видео…"
                    : review.phase === "restoring"
                      ? "Восстанавливаем проверку…"
                      : review.busy
                        ? "Проверяем запись…"
                        : backendIsDemo
                          ? "Запустить демопроверку"
                          : "Проверить видео"}
                  {!review.busy && <ArrowRight size={18} />}
                </button>
                <p className="privacy-note">
                  <ShieldCheck size={15} />
                  <span>
                    Без облачных AI-сервисов. Общий бюджет — до 5 минут.
                  </span>
                </p>
              </div>
              <input
                ref={input}
                id="video-file"
                className="visually-hidden"
                type="file"
                accept=".mov,.mp4,video/quicktime,video/mp4"
                disabled={review.busy}
                tabIndex={-1}
                aria-label="Видео для проверки"
                onChange={(e) => {
                  selectFile(e.target.files?.[0], reattaching.current);
                  e.target.value = "";
                }}
              />
              {file ? (
                <VideoReview
                  ref={preview}
                  file={file}
                  events={review.job?.violations ?? []}
                  activeEvent={activeEvent}
                  onSelect={setActiveEvent}
                  onRemove={() => {
                    setFile(null);
                    setFileError("");
                  }}
                  disabled={review.busy}
                />
              ) : review.job ? (
                <div className="restored-file">
                  <FileVideo2 size={27} />
                  <strong>{review.job.filename}</strong>
                  <p>
                    Проверка восстановлена. Браузер не сохраняет доступ к
                    локальному видео после обновления страницы.
                  </p>
                  <button
                    className="button secondary"
                    onClick={() => pick(true)}
                    disabled={review.busy}
                  >
                    Выбрать файл для просмотра
                  </button>
                  <small>
                    Это не запустит анализ повторно. Имя и размер помогают
                    выбрать исходную запись, но не подтверждают её содержимое.
                  </small>
                </div>
              ) : (
                <button
                  type="button"
                  disabled={review.busy}
                  className={`dropzone ${dragging ? "dragging" : ""}`}
                  onClick={() => pick()}
                  onDragOver={(e) => {
                    e.preventDefault();
                    if (!review.busy) setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDragging(false);
                    selectFile(e.dataTransfer.files[0]);
                  }}
                >
                  <div className="upload-symbol">
                    <Upload size={29} strokeWidth={1.5} />
                  </div>
                  <strong>
                    {dragging
                      ? "Отпустите файл здесь"
                      : "Перетащите видео сюда"}
                  </strong>
                  <span className="file-pick">
                    Выбрать видео
                    <ArrowRight size={17} />
                  </span>
                  <small>
                    До 10 минут ·{" "}
                    {backendIsDemo
                      ? "синтетическая запись для теста"
                      : "запись кассовых операций"}
                  </small>
                </button>
              )}
              {fileError && (
                <div className="form-error" role="alert">
                  <AlertCircle size={18} />
                  <span>{fileError}</span>
                </div>
              )}
              <div className="key-field">
                <label htmlFor="api-key">
                  <KeyRound size={16} />
                  Ключ доступа к API
                </label>
                <div className="input-wrap">
                  <input
                    ref={keyInput}
                    id="api-key"
                    type={showKey ? "text" : "password"}
                    value={key}
                    onChange={(e) => setKey(e.target.value)}
                    placeholder="Введите ключ сервиса"
                    autoComplete="off"
                    spellCheck={false}
                    disabled={review.busy}
                    aria-invalid={review.issue?.kind === "auth"}
                    aria-describedby="key-hint"
                  />
                  <button
                    className="icon-button"
                    aria-label={showKey ? "Скрыть ключ" : "Показать ключ"}
                    type="button"
                    onClick={() => setShowKey(!showKey)}
                  >
                    {showKey ? <EyeOff size={19} /> : <Eye size={19} />}
                  </button>
                </div>
                <small id="key-hint">
                  Хранится в этой вкладке, не включается в сборку сайта.
                </small>
              </div>
              {backendIsDemo && (
                <div className="scenario-select">
                  <label htmlFor="demo-scenario">Тестовый сценарий</label>
                  <select
                    id="demo-scenario"
                    value={scenario}
                    onChange={(e) => setScenario(e.target.value)}
                    disabled={review.busy}
                  >
                    {DEMO_SCENARIOS.map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </section>
            <ResultPanel
              job={review.job}
              phase={review.phase}
              issue={review.issue}
              activeEvent={activeEvent}
              onSelect={chooseEvent}
              onSeek={(time) => preview.current?.seek(time)}
              canPlay={!!file}
              onFrame={setFrame}
              onResume={review.resume}
              canResume={review.canResume}
              onReset={reset}
              hasKey={!!key.trim()}
            />
          </div>
          <details className="how-it-works" ref={details}>
            <summary>
              <Info size={18} />
              Как проходит проверка
              <ChevronRight size={17} />
            </summary>
            <div className="how-grid">
              <div>
                <h3>Загрузите запись</h3>
                <p>
                  Укажите ключ доступа и выберите файл. Время загрузки и
                  ожидания в очереди входит в общий бюджет проверки.
                </p>
              </div>
              <div>
                <h3>Вернитесь к результату</h3>
                <p>
                  Текущая проверка восстановится после обновления вкладки. Для
                  просмотра исходного видео нужно снова выбрать локальный файл.
                </p>
              </div>
              <div>
                <h3>Изучите доказательства</h3>
                <p>
                  Увеличивайте кадры и переходите к отметкам событий. ML2
                  получает наблюдения и кадры, а не исходный ролик.
                </p>
              </div>
            </div>
            {service.readiness && (
              <div className="component-status">
                <h3>Проверка компонентов</h3>
                <ul>
                  {Object.entries(service.readiness.checks).map(
                    ([name, check]) => (
                      <li key={name}>
                        <strong>
                          {checkNames[name] ?? name}:{" "}
                          {check.ready ? "доступно" : "недоступно"}
                        </strong>
                        <span>{check.detail}</span>
                      </li>
                    ),
                  )}
                </ul>
                <p>
                  Доступность порта ML-сервиса не подтверждает, что модель
                  загружена или правильно анализирует видео.
                </p>
              </div>
            )}
          </details>
          <footer>
            <span>Cashier Guard</span>
            <span>Помощь в проверке · окончательное решение за человеком</span>
          </footer>
        </main>
      </div>
      {frame && <FrameDialog frame={frame} onClose={() => setFrame(null)} />}
    </div>
  );
}
