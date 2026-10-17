import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  ChevronRight,
  BookOpen,
  Cpu,
  Terminal,
  Video,
  History,
  BarChart3,
  Eye,
  Info,
  LoaderCircle,
  RefreshCw,
  ScanLine,
  ShieldCheck,
  Settings,
  Upload,
} from "lucide-react";
import type { Frame } from "./api";
import { readKey, useReview } from "./hooks/useReview";
import { useServiceStatus } from "./hooks/useServiceStatus";
import {
  HistoryPanel,
  AnalyticsPanel,
  emptyFilters,
} from "./components/HistoryAnalytics";
import type { HistoryFilters } from "./components/HistoryAnalytics";
import { ArchivedVideo } from "./components/ArchivedVideo";
import { FrameDialog } from "./components/FrameDialog";
import { ResultPanel } from "./components/ResultPanel";
import { ReviewSummary } from "./components/ReviewSummary";
import { SettingsPanel } from "./components/SettingsPanel";
import { WorkspaceSections } from "./components/WorkspaceSections";
import type { WorkspaceTab } from "./components/WorkspaceSections";
import { VideoReview } from "./components/VideoReview";
import type { VideoHandle } from "./components/VideoReview";
import {
  isSupportedVideoFilename,
  VIDEO_ACCEPT,
  VIDEO_FORMATS,
} from "./videoFormats";

const sections = [
  { id: "workspace", label: "Проверка видео", icon: Video },
  { id: "history", label: "История", icon: History },
  { id: "analytics", label: "Аналитика", icon: BarChart3 },
  { id: "regulations", label: "Нормативы РК", icon: BookOpen },
  { id: "api", label: "API", icon: Terminal },
  { id: "architecture", label: "Архитектура", icon: Cpu },
  { id: "settings", label: "Настройки", icon: Settings },
] as const;

export default function App() {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("workspace");
  const [historyFilters, setHistoryFilters] =
    useState<HistoryFilters>(emptyFilters);
  const [key, setKey] = useState(readKey);
  const [file, setFile] = useState<File | null>(null);
  const [canPreview, setCanPreview] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [fileError, setFileError] = useState("");
  const [activeEvent, setActiveEvent] = useState(0);
  const [frame, setFrame] = useState<Frame | null>(null);
  const review = useReview(key);
  const service = useServiceStatus();
  const input = useRef<HTMLInputElement>(null);
  const details = useRef<HTMLDetailsElement>(null);
  const preview = useRef<VideoHandle>(null);
  const reattaching = useRef(false);
  const maxMB = service.health?.max_upload_mb ?? 100;
  const analysisAvailable =
    service.health?.mode === "live" &&
    service.readiness?.mode === "live" &&
    service.readiness.ready === true;

  useEffect(() => {
    setActiveEvent(0);
    setFrame(null);
  }, [review.job?.job_id]);

  useEffect(() => {
    const heading = Array.from(
      document.querySelectorAll<HTMLElement>("main h1"),
    ).find((item) => !item.closest("[hidden]"));
    if (heading) {
      heading.tabIndex = -1;
      heading.focus({ preventScroll: true });
    }
  }, [activeTab]);

  function reset() {
    review.reset();
    setFile(null);
    setCanPreview(false);
    setFileError("");
    setActiveEvent(0);
    setFrame(null);
    if (input.current) input.current.value = "";
  }
  function selectFile(next?: File, attach = false) {
    if (!next || review.busy) return;
    if (!isSupportedVideoFilename(next.name)) {
      setFileError(
        `Поддерживаются ${VIDEO_FORMATS}. Выберите один из этих форматов.`,
      );
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
    setCanPreview(false);
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
  const canSubmit = !!file && !!key.trim() && analysisAvailable && !review.busy;
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
      <header className="topbar">
        <div className="header-inner">
          <div className="brand">
            <div className="brand-symbol">
              <Eye size={21} strokeWidth={1.8} />
            </div>
            <div>
              <div className="brand-name">
                Cashier<span>Guard</span>
              </div>
              <small>AI-контроль кассовой дисциплины</small>
            </div>
          </div>
          <nav className="top-navigation" aria-label="Разделы">
            {sections.map((section) => {
              const Icon = section.icon;
              return (
                <button
                  key={section.id}
                  onClick={() => setActiveTab(section.id)}
                  aria-current={activeTab === section.id ? "page" : undefined}
                >
                  <Icon size={15} />
                  <span>{section.label}</span>
                </button>
              );
            })}
          </nav>
        </div>
      </header>
      <div className="main-shell">
        <main id="main">
          <div className="breadcrumb">
            Рабочее пространство
            <ChevronRight size={13} />
            <span>
              {sections.find((section) => section.id === activeTab)?.label}
            </span>
          </div>
          <div hidden={activeTab !== "workspace"}>
            <div className="page-heading">
              <div>
                <h1>Проверка видео</h1>
                <p>
                  События, точное время и кадры для проверки кассовых операций.
                </p>
              </div>
            </div>
            <div className="workspace-toolbar">
              <div className="toolbar-file">
                <Video size={21} />
                <div>
                  <strong>Видеозапись кассовых операций</strong>
                  <small>
                    {file
                      ? `Выбрано: ${file.name}`
                      : review.job
                        ? `Сохранённая проверка: ${review.job.filename}`
                        : "Выберите запись на компьютере · до 10 минут"}
                  </small>
                </div>
              </div>
              <div className="toolbar-actions">
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
                <button
                  className="button primary"
                  onClick={() => pick()}
                  disabled={review.busy}
                >
                  <Upload size={16} />
                  {file ? "Заменить видео" : "Загрузить видео"}
                </button>
              </div>
            </div>
            {service.checked && !analysisAvailable && (
              <div className="alert error readiness-alert" role="alert">
                <AlertCircle size={20} />
                <div>
                  <strong>
                    {!service.health
                      ? "Сервер недоступен"
                      : "Анализ видео пока недоступен"}
                  </strong>
                  <p>
                    {!service.health
                      ? "Проверьте подключение и запуск backend. Сохранённая проверка не потеряна."
                      : service.health.mode !== "live" ||
                          service.readiness?.mode === "demo"
                        ? "Реальные модели анализа ещё не подключены. Вы можете выбрать и просмотреть видео."
                        : !service.readiness
                          ? "Не удалось проверить готовность анализа. Повторите проверку подключения."
                          : "Проверьте перечисленные компоненты. Пока доступен только просмотр видео."}
                  </p>
                  {service.readiness &&
                    Object.values(service.readiness.checks).some(
                      (check) => !check.ready,
                    ) && (
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

            {review.phase === "done" && !review.issue && review.job && (
              <ReviewSummary
                job={review.job}
                onShowApi={() => setActiveTab("api")}
              />
            )}
            <div className="workspace">
              <section
                className="upload-panel"
                aria-labelledby="upload-heading"
              >
                <div className="panel-heading">
                  <h2 id="upload-heading">Видеозапись</h2>
                  <span>
                    {VIDEO_FORMATS} · до {maxMB} МБ
                  </span>
                </div>
                <input
                  ref={input}
                  id="video-file"
                  className="visually-hidden"
                  type="file"
                  accept={VIDEO_ACCEPT}
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
                    normalizedDuration={review.job?.duration_sec}
                    sourceTimeOffset={review.job?.source_time_offset_sec}
                    onSelect={setActiveEvent}
                    onPreviewAvailabilityChange={setCanPreview}
                    onRemove={() => {
                      setFile(null);
                      setCanPreview(false);
                      setFileError("");
                    }}
                    disabled={review.busy}
                  />
                ) : review.job ? (
                  <ArchivedVideo
                    ref={preview}
                    job={review.job}
                    apiKey={key}
                    activeEvent={activeEvent}
                    onSelect={setActiveEvent}
                    onPreviewAvailabilityChange={setCanPreview}
                    onPick={() => pick(true)}
                    disabled={review.busy}
                  />
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
                    <small>До 10 минут · запись кассовых операций</small>
                  </button>
                )}
                {fileError && (
                  <div className="form-error" role="alert">
                    <AlertCircle size={18} />
                    <span>{fileError}</span>
                  </div>
                )}
                {file && (
                  <div className="form-actions">
                    {!key.trim() && (
                      <div className="connection-prompt" id="connection-prompt">
                        <p>Настройте подключение для проверки видео</p>
                        <a
                          href="#settings"
                          onClick={(event) => {
                            event.preventDefault();
                            setActiveTab("settings");
                          }}
                        >
                          Открыть настройки
                        </a>
                      </div>
                    )}
                    <button
                      className="button primary analyze-button"
                      onClick={() => {
                        if (file && canSubmit) {
                          setFileError("");
                          void review.submit(file);
                        }
                      }}
                      disabled={!canSubmit}
                      aria-describedby={
                        !key.trim() ? "connection-prompt" : undefined
                      }
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
                            ? review.job?.stage === "preparing"
                              ? "Подготавливаем видео…"
                              : "Проверяем запись…"
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
                )}
              </section>
              <ResultPanel
                hideSummary
                job={review.job}
                phase={review.phase}
                issue={review.issue}
                activeEvent={activeEvent}
                onSelect={chooseEvent}
                onSeek={(time) => preview.current?.seek(time)}
                canPlay={!!file && canPreview}
                onFrame={setFrame}
                onResume={review.resume}
                canResume={review.canResume}
                onReset={reset}
                hasKey={!!key.trim()}
                onOpenSettings={() => setActiveTab("settings")}
                apiKey={key}
                onReviewSaved={(eventId, value) => {
                  if (review.job)
                    review.applyHumanReview(review.job.job_id, eventId, value);
                }}
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
                    Выберите MOV, MP4, AVI, MKV или WEBM и нажмите «Проверить
                    видео». Перед анализом видео преобразуется в MP4. Загрузка,
                    очередь и преобразование входят в общий бюджет проверки.
                  </p>
                </div>
                <div>
                  <h3>Вернитесь к результату</h3>
                  <p>
                    Проверки доступны в истории после обновления страницы.
                    Сохранённое видео открывается без нового анализа. Результаты
                    и ролики имеют отдельные сроки хранения, указанные в истории
                    и карточке проверки.
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
          </div>
          {activeTab === "settings" && (
            <SettingsPanel savedKey={key} onSave={setKey} busy={review.busy} />
          )}
          {activeTab === "history" && (
            <HistoryPanel
              apiKey={key}
              filters={historyFilters}
              onFilters={setHistoryFilters}
              canOpen={!review.busy}
              onSettings={() => setActiveTab("settings")}
              onOpen={(jobId) => {
                setFile(null);
                setCanPreview(false);
                setFileError("");
                setFrame(null);
                setActiveEvent(0);
                review.open(jobId);
                setActiveTab("workspace");
              }}
              onDeleted={(jobId) => {
                if (review.restoredId === jobId || review.job?.job_id === jobId)
                  reset();
              }}
            />
          )}
          {activeTab === "analytics" && (
            <AnalyticsPanel
              apiKey={key}
              onSettings={() => setActiveTab("settings")}
              onDrill={(filters) => {
                setHistoryFilters(filters);
                setActiveTab("history");
              }}
            />
          )}
          {activeTab !== "workspace" &&
            activeTab !== "settings" &&
            activeTab !== "history" &&
            activeTab !== "analytics" && (
              <WorkspaceSections tab={activeTab} job={review.job} />
            )}
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
