import { useEffect, useState } from "react";
import { BarChart3, History, LoaderCircle, Search } from "lucide-react";
import { request } from "../api";
import type { Analytics, HistoryPage, HistoryItem } from "../api";

export type HistoryFilters = {
  search: string;
  status: string;
  period: string;
  from: string;
  to: string;
  category_id: string;
  categoryLabel: string;
  mode: string;
};
export const emptyFilters: HistoryFilters = {
  search: "",
  status: "",
  period: "all",
  from: "",
  to: "",
  category_id: "",
  categoryLabel: "",
  mode: "",
};
const dateText = (value: string) => new Date(value).toLocaleString("ru-RU");
const statusLabels = {
  processing: "В обработке",
  done: "Завершено",
  failed: "Ошибка обработки",
};
function dateInput(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
export function periodDates(period: string, from = "", to = "") {
  if (period === "all")
    return { from: "", to: "", query: {} as Record<string, string> };
  if (period !== "custom") {
    const end = new Date();
    const start = new Date(end);
    start.setDate(start.getDate() - (period === "7" ? 6 : 29));
    from = dateInput(start);
    to = dateInput(end);
  }
  if (!from || !to || from > to)
    throw new Error("Укажите корректное начало и окончание периода.");
  const start = new Date(`${from}T00:00:00`),
    end = new Date(`${to}T00:00:00`);
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()))
    throw new Error("Проверьте даты периода.");
  end.setDate(end.getDate() + 1);
  return {
    from,
    to,
    query: { date_from: start.toISOString(), date_to: end.toISOString() },
  };
}
function useRemote<T>(path: string, apiKey: string, refresh: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    const cancel = new AbortController();
    setData(null);
    setError("");
    if (!apiKey.trim()) {
      setLoading(false);
      return;
    }
    setLoading(true);
    void request<T>(path, apiKey.trim(), { signal: cancel.signal, retries: 1 })
      .then((value) => {
        const data = value as Record<string, unknown> | null;
        const count = (n: unknown) =>
          typeof n === "number" && Number.isSafeInteger(n) && n >= 0;
        const valid =
          data &&
          (path.startsWith("/jobs?")
            ? Array.isArray(data.items) &&
              count(data.total) &&
              data.items.every(
                (item) =>
                  item &&
                  typeof item.job_id === "string" &&
                  typeof item.filename === "string" &&
                  ["processing", "done", "failed"].includes(item.status) &&
                  [
                    item.red_count,
                    item.yellow_count,
                    item.unreviewed_count,
                  ].every(count),
              )
            : [
                data.successful_videos,
                data.videos_with_events,
                data.detected_events,
                data.confirmed_events,
                data.rejected_events,
                data.unreviewed_events,
              ].every(count) &&
              Array.isArray(data.top_types) &&
              data.top_types.every(
                (item) =>
                  item &&
                  typeof item.category_id === "string" &&
                  typeof item.type === "string" &&
                  count(item.detected) &&
                  count(item.confirmed),
              ));
        if (!valid)
          throw new Error(
            "Ответ сервера не соответствует контракту. Данные не подтверждены.",
          );
        if (!cancel.signal.aborted) setData(value);
      })
      .catch((problem: Error) => {
        if (!cancel.signal.aborted) setError(problem.message);
      })
      .finally(() => {
        if (!cancel.signal.aborted) setLoading(false);
      });
    return () => cancel.abort();
  }, [path, apiKey, refresh]);
  return { data, error, loading };
}
function AccessNotice({ onSettings }: { onSettings: () => void }) {
  return (
    <div className="section-empty">
      <h2>Настройте подключение</h2>
      <p>Для доступа к сохранённым проверкам нужен ключ API.</p>
      <a
        href="#settings"
        onClick={(e) => {
          e.preventDefault();
          onSettings();
        }}
      >
        Открыть настройки
      </a>
    </div>
  );
}
function LoadError({
  error,
  retry,
  onSettings,
}: {
  error: string;
  retry: () => void;
  onSettings: () => void;
}) {
  return (
    <div className="section-empty" role="alert">
      <h2>Не удалось загрузить данные</h2>
      <p>{error}</p>
      <div className="settings-actions">
        <button className="button secondary" onClick={retry}>
          Повторить
        </button>
        <a
          href="#settings"
          onClick={(e) => {
            e.preventDefault();
            onSettings();
          }}
        >
          Открыть настройки
        </a>
      </div>
    </div>
  );
}
function PeriodFields({
  value,
  from,
  to,
  onChange,
  allowAll = true,
}: {
  allowAll?: boolean;
  value: string;
  from: string;
  to: string;
  onChange: (next: { period?: string; from?: string; to?: string }) => void;
}) {
  return (
    <>
      <label>
        Период
        <select
          value={value}
          onChange={(e) => onChange({ period: e.target.value })}
        >
          {allowAll && <option value="all">Всё время</option>}
          <option value="7">7 дней</option>
          <option value="30">30 дней</option>
          <option value="custom">Произвольные даты</option>
        </select>
      </label>
      {value === "custom" && (
        <>
          <label>
            С даты
            <input
              type="date"
              value={from}
              onChange={(e) => onChange({ from: e.target.value })}
              required
            />
          </label>
          <label>
            По дату
            <input
              type="date"
              value={to}
              min={from}
              onChange={(e) => onChange({ to: e.target.value })}
              required
            />
          </label>
        </>
      )}
    </>
  );
}
export function HistoryPanel({
  apiKey,
  filters,
  onFilters,
  onOpen,
  onDeleted,
  onSettings,
  canOpen,
}: {
  apiKey: string;
  filters: HistoryFilters;
  onFilters: (filters: HistoryFilters) => void;
  onOpen: (jobId: string) => void;
  onDeleted: (jobId: string) => void;
  onSettings: () => void;
  canOpen: boolean;
}) {
  const [draft, setDraft] = useState(filters);
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [formError, setFormError] = useState("");
  const [deleteId, setDeleteId] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [mutationError, setMutationError] = useState("");
  const query = new URLSearchParams({ page: String(page), page_size: "10" });
  const dates = periodDates(filters.period, filters.from, filters.to);
  for (const [name, value] of Object.entries({
    search: filters.search,
    status: filters.status,
    category_id: filters.category_id,
    mode: filters.mode,
    ...dates.query,
  }))
    if (value) query.set(name, value);
  const { data, error, loading } = useRemote<HistoryPage>(
    `/jobs?${query}`,
    apiKey,
    refresh,
  );
  useEffect(() => {
    if (data && data.total > 0 && !data.items.length && page > 1)
      setPage(page - 1);
  }, [data, page]);
  async function remove(item: HistoryItem) {
    if (deleting) return;
    setDeleting(true);
    setMutationError("");
    try {
      await request(`/jobs/${encodeURIComponent(item.job_id)}`, apiKey.trim(), {
        method: "DELETE",
      });
      setDeleteId("");
      onDeleted(item.job_id);
      setRefresh((value) => value + 1);
    } catch (problem) {
      setMutationError(
        problem instanceof Error
          ? problem.message
          : "Не удалось удалить запись.",
      );
    } finally {
      setDeleting(false);
    }
  }
  return (
    <section className="section-stack" aria-labelledby="history-heading">
      <div className="section-intro">
        <History size={23} />
        <div>
          <h1 id="history-heading">История проверок</h1>
          <p>
            Сохранённые результаты и решения проверяющего. Открытие не запускает
            анализ заново.
          </p>
        </div>
      </div>
      {!apiKey.trim() ? (
        <AccessNotice onSettings={onSettings} />
      ) : (
        <>
          <form
            className="history-filters"
            onSubmit={(e) => {
              e.preventDefault();
              try {
                periodDates(draft.period, draft.from, draft.to);
                setFormError("");
                onFilters(draft);
                setPage(1);
              } catch (problem) {
                setFormError((problem as Error).message);
              }
            }}
          >
            <label className="history-search">
              Название видео
              <input
                type="search"
                value={draft.search}
                placeholder="Поиск по названию"
                maxLength={255}
                onChange={(e) => setDraft({ ...draft, search: e.target.value })}
              />
            </label>
            <PeriodFields
              value={draft.period}
              from={draft.from}
              to={draft.to}
              onChange={(value) => setDraft({ ...draft, ...value })}
            />
            <label>
              Статус
              <select
                value={draft.status}
                onChange={(e) => setDraft({ ...draft, status: e.target.value })}
              >
                <option value="">Все статусы</option>
                {Object.entries(statusLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <button className="button primary" type="submit">
              <Search size={16} />
              Применить
            </button>
            <button
              className="button secondary"
              type="button"
              onClick={() => {
                setDraft(emptyFilters);
                onFilters(emptyFilters);
                setPage(1);
                setFormError("");
              }}
            >
              Сбросить
            </button>
            {formError && (
              <p role="alert" className="filter-error">
                {formError}
              </p>
            )}
          </form>
          {filters.category_id && (
            <div className="filter-summary">
              Тип события: <strong>{filters.categoryLabel}</strong>. Только
              завершённые реальные проверки.
              <button
                className="text-button"
                onClick={() => {
                  const next = {
                    ...filters,
                    category_id: "",
                    categoryLabel: "",
                    mode: "",
                  };
                  setDraft(next);
                  onFilters(next);
                  setPage(1);
                }}
              >
                Убрать фильтр типа
              </button>
            </div>
          )}
          {!canOpen && (
            <p className="review-note">
              Открытие другой проверки будет доступно после завершения текущей
              загрузки или обработки.
            </p>
          )}
          {loading && (
            <p role="status" className="loading-state">
              <LoaderCircle size={20} className="spin" />
              Загружаем историю…
            </p>
          )}
          {error && (
            <LoadError
              error={error}
              retry={() => setRefresh((n) => n + 1)}
              onSettings={onSettings}
            />
          )}
          {data && !data.items.length && (
            <div className="section-empty">
              <History size={30} />
              <h2>
                {data.total
                  ? "На этой странице нет записей"
                  : "Проверок пока нет"}
              </h2>
              <p>
                Загрузите видео или измените фильтры поиска. Здесь появятся
                сохранённые результаты.
              </p>
            </div>
          )}
          {data && data.items.length > 0 && (
            <>
              <p className="review-note" role="status">
                Найдено проверок: {data.total}
              </p>
              <ol className="history-list">
                {data.items.map((item) => (
                  <li key={item.job_id}>
                    <article className="history-item">
                      <div className="history-file">
                        <h2>{item.filename}</h2>
                        <time dateTime={item.created_at}>
                          {dateText(item.created_at)}
                        </time>
                        <span className="history-status">
                          {statusLabels[item.status]}
                          {item.mode === "demo" ? " · Демо" : ""}
                        </span>
                        <small>Результат до {dateText(item.expires_at)}</small>
                        <small>
                          {item.video_available && item.video_expires_at
                            ? `Видео до ${dateText(item.video_expires_at)}`
                            : "Ролик недоступен; результат хранится отдельно"}
                        </small>
                      </div>
                      <dl className="history-counts">
                        <div>
                          <dt>Красных</dt>
                          <dd>{item.red_count}</dd>
                        </div>
                        <div>
                          <dt>Жёлтых</dt>
                          <dd>{item.yellow_count}</dd>
                        </div>
                        <div>
                          <dt>Не рассмотрено</dt>
                          <dd>{item.unreviewed_count}</dd>
                        </div>
                      </dl>
                      <div className="history-actions">
                        <button
                          className="button secondary"
                          disabled={!canOpen}
                          onClick={() => onOpen(item.job_id)}
                        >
                          Открыть проверку
                        </button>
                        <button
                          className="text-button"
                          disabled={item.status === "processing" || deleting}
                          onClick={() => {
                            setDeleteId(item.job_id);
                            setMutationError("");
                          }}
                        >
                          Удалить
                        </button>
                      </div>
                      {deleteId === item.job_id && (
                        <div className="delete-confirmation">
                          <p>
                            Удалить эту проверку, решения и сохранённое видео?
                          </p>
                          <div className="settings-actions">
                            <button
                              className="button secondary"
                              disabled={deleting}
                              onClick={() => void remove(item)}
                            >
                              {deleting ? "Удаляем…" : "Удалить проверку"}
                            </button>
                            <button
                              className="button secondary"
                              disabled={deleting}
                              onClick={() => setDeleteId("")}
                            >
                              Отмена
                            </button>
                          </div>
                          {mutationError && (
                            <p className="form-error" role="alert">
                              {mutationError}
                            </p>
                          )}
                        </div>
                      )}
                    </article>
                  </li>
                ))}
              </ol>
            </>
          )}
          {data && data.total > 10 && (
            <nav className="pagination" aria-label="Страницы истории">
              <button
                className="button secondary"
                disabled={page <= 1 || loading}
                onClick={() => setPage(page - 1)}
              >
                Назад
              </button>
              <span>
                Страница {page} из {Math.ceil(data.total / 10)}
              </span>
              <button
                className="button secondary"
                disabled={page * 10 >= data.total || loading}
                onClick={() => setPage(page + 1)}
              >
                Далее
              </button>
            </nav>
          )}
        </>
      )}
    </section>
  );
}

export function AnalyticsPanel({
  apiKey,
  onSettings,
  onDrill,
}: {
  apiKey: string;
  onSettings: () => void;
  onDrill: (filters: HistoryFilters) => void;
}) {
  const [period, setPeriod] = useState({ period: "7", from: "", to: "" });
  const [applied, setApplied] = useState(() => periodDates("7"));
  const [formError, setFormError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const query = new URLSearchParams(applied.query);
  const { data, error, loading } = useRemote<Analytics>(
    `/analytics?${query}`,
    apiKey,
    refresh,
  );
  const maximum = Math.max(
    1,
    ...(data?.top_types.map((item) => item.detected) ?? []),
  );
  return (
    <section className="section-stack" aria-labelledby="analytics-heading">
      <div className="section-intro">
        <BarChart3 size={23} />
        <div>
          <h1 id="analytics-heading">Аналитика</h1>
          <p>События модели и решения человека учитываются отдельно.</p>
        </div>
      </div>
      {!apiKey.trim() ? (
        <AccessNotice onSettings={onSettings} />
      ) : (
        <>
          <form
            className="history-filters"
            onSubmit={(e) => {
              e.preventDefault();
              try {
                setApplied(periodDates(period.period, period.from, period.to));
                setFormError("");
              } catch (problem) {
                setFormError((problem as Error).message);
              }
            }}
          >
            <PeriodFields
              allowAll={false}
              value={period.period}
              from={period.from}
              to={period.to}
              onChange={(value) => setPeriod({ ...period, ...value })}
            />
            <button className="button primary" type="submit">
              Показать
            </button>
            {formError && (
              <p className="filter-error" role="alert">
                {formError}
              </p>
            )}
          </form>
          <p className="review-note">
            Период по дате загрузки, включая выбранную конечную дату. Только
            завершённые реальные проверки. Ошибки, незавершённые и
            демонстрационные результаты не учитываются.
          </p>
          {loading && (
            <p role="status" className="loading-state">
              <LoaderCircle className="spin" size={20} />
              Загружаем аналитику…
            </p>
          )}
          {error && (
            <LoadError
              error={error}
              retry={() => setRefresh((n) => n + 1)}
              onSettings={onSettings}
            />
          )}
          {data && (
            <>
              <section
                className="analytics-group"
                aria-labelledby="model-stats"
              >
                <h2 id="model-stats">Обнаружено моделью</h2>
                <dl className="analytics-metrics">
                  <div>
                    <dt>Успешно проверенных видео</dt>
                    <dd>{data.successful_videos}</dd>
                  </div>
                  <div>
                    <dt>Видео с событиями</dt>
                    <dd>{data.videos_with_events}</dd>
                  </div>
                  <div>
                    <dt>Обнаружено событий</dt>
                    <dd>{data.detected_events}</dd>
                  </div>
                </dl>
              </section>
              <section
                className="analytics-group"
                aria-labelledby="human-stats"
              >
                <h2 id="human-stats">Решения человека</h2>
                <dl className="analytics-metrics">
                  <div>
                    <dt>Подтверждено человеком</dt>
                    <dd>{data.confirmed_events}</dd>
                  </div>
                  <div>
                    <dt>Отклонено человеком</dt>
                    <dd>{data.rejected_events}</dd>
                  </div>
                  <div>
                    <dt>Ещё не рассмотрено</dt>
                    <dd>{data.unreviewed_events}</dd>
                  </div>
                </dl>
              </section>
              <section className="analytics-types" aria-labelledby="top-types">
                <h2 id="top-types">Топ-3 типов событий</h2>
                <p className="review-note">
                  Точные типы из ответа модели. Столбцы показывают обнаруженные
                  события, а не кадры.
                </p>
                {!data.top_types.length ? (
                  <p className="analytics-empty">
                    За выбранный период событий нет.
                  </p>
                ) : (
                  <ol>
                    {data.top_types.map((item) => (
                      <li key={item.category_id}>
                        <button
                          onClick={() =>
                            onDrill({
                              ...emptyFilters,
                              period: applied.from ? "custom" : "all",
                              from: applied.from,
                              to: applied.to,
                              status: "done",
                              mode: "live",
                              category_id: item.category_id,
                              categoryLabel: item.type,
                            })
                          }
                        >
                          <span className="type-bar-title">
                            <strong>{item.type}</strong>
                            <span>
                              Обнаружено: {item.detected} · Подтверждено:{" "}
                              {item.confirmed}
                            </span>
                          </span>
                          <span className="type-bar-track" aria-hidden="true">
                            <span
                              style={{
                                width: `${(item.detected / maximum) * 100}%`,
                              }}
                            />
                          </span>
                          <span className="type-link">Показать проверки →</span>
                        </button>
                      </li>
                    ))}
                  </ol>
                )}
              </section>
            </>
          )}
        </>
      )}
    </section>
  );
}
