import { useEffect, useState } from "react";
import { ListChecks, LoaderCircle } from "lucide-react";
import { request, timecode } from "../api";
import type { QueuePage, QueueEvent, QueueOptions } from "../api";
import { PeriodFields, periodDates } from "./HistoryAnalytics";
export type QueueFilters = {
  period: string;
  from: string;
  to: string;
  category_id: string;
  tag: string;
};
export const defaultQueueFilters: QueueFilters = {
  period: "all",
  from: "",
  to: "",
  category_id: "",
  tag: "",
};
export function queueQuery(filters: QueueFilters) {
  const query = new URLSearchParams(
    periodDates(filters.period, filters.from, filters.to).query,
  );
  if (filters.category_id) query.set("category_id", filters.category_id);
  if (filters.tag) query.set("tag", filters.tag);
  return query;
}
export function useQueue(
  apiKey: string,
  filters: QueueFilters,
  page = 1,
  revision = 0,
  exclude = "",
) {
  const [data, setData] = useState<QueuePage | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false),
    [retry, setRetry] = useState(0);
  const query = queueQuery(filters);
  query.set("page", String(page));
  query.set("page_size", exclude ? "1" : "8");
  if (exclude) query.set("exclude_event_id", exclude);
  const path = `/review-queue?${query}`;
  useEffect(() => {
    setData(null);
    setError("");
    if (!apiKey.trim()) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    void request<QueuePage>(path, apiKey, {
      signal: controller.signal,
      retries: 1,
    })
      .then((v) => {
        if (
          !v ||
          !Array.isArray(v.items) ||
          ![v.total, v.total_events, v.reviewed_events].every(
            (n) => Number.isSafeInteger(n) && n >= 0,
          )
        )
          throw new Error("Ответ очереди не соответствует контракту.");
        if (!controller.signal.aborted) setData(v);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, apiKey, revision, retry]);
  return { data, error, loading, retry: () => setRetry((n) => n + 1) };
}
export function QueueNavigation({
  apiKey,
  filters,
  eventId,
  revision,
  onOpen,
}: {
  apiKey: string;
  filters: QueueFilters;
  eventId: string;
  revision: number;
  onOpen: (item: QueueEvent) => void;
}) {
  const { data, error, loading, retry } = useQueue(
    apiKey,
    filters,
    1,
    revision,
    eventId,
  );
  return (
    <aside
      className="queue-navigation"
      aria-label="Переход по непроверенным событиям"
    >
      <div>
        <strong>На рассмотрении</strong>
        <p role="status">
          {loading
            ? "Обновляем прогресс…"
            : data
              ? `Рассмотрено ${data.reviewed_events} из ${data.total_events}`
              : "Не удалось обновить прогресс"}
        </p>
      </div>
      <button
        className="button secondary"
        disabled={loading || !data?.items[0]}
        onClick={() => {
          if (data?.items[0]) onOpen(data.items[0]);
        }}
      >
        Следующее непроверенное
      </button>
      {data && !data.items.length && (
        <p className="review-note">
          Других непроверенных событий по этим фильтрам нет.
        </p>
      )}
      {error && (
        <div role="alert">
          <p>{error}</p>
          <button className="text-button" onClick={retry}>
            Обновить очередь
          </button>
        </div>
      )}
      <small>
        Переход не сохраняет решение автоматически. Несохранённый комментарий
        останется черновиком этой вкладки.
      </small>
    </aside>
  );
}
export function ReviewQueuePanel({
  apiKey,
  filters,
  onFilters,
  onOpen,
  onSettings,
  revision,
}: {
  apiKey: string;
  filters: QueueFilters;
  onFilters: (f: QueueFilters) => void;
  onOpen: (e: QueueEvent) => void;
  onSettings: () => void;
  revision: number;
}) {
  const [draft, setDraft] = useState(filters),
    [page, setPage] = useState(1),
    [formError, setFormError] = useState(""),
    [options, setOptions] = useState<QueueOptions>({ types: [], tags: [] });
  const { data, error, loading, retry } = useQueue(
    apiKey,
    filters,
    page,
    revision,
  );
  useEffect(() => {
    if (!apiKey) return;
    const cancel = new AbortController();
    void request<QueueOptions>("/review-queue/options", apiKey, {
      signal: cancel.signal,
    })
      .then((v) => {
        if (!cancel.signal.aborted) setOptions(v);
      })
      .catch(() => {
        /* List errors remain visible; exact tag input also works without options. */
      });
    return () => cancel.abort();
  }, [apiKey, revision]);
  useEffect(() => {
    if (data && page > 1 && !data.items.length) setPage((n) => n - 1);
  }, [data, page]);
  return (
    <section className="section-stack" aria-labelledby="queue-heading">
      <div className="section-intro">
        <ListChecks size={24} />
        <div>
          <h1 id="queue-heading">На рассмотрении</h1>
          <p>
            События без сохранённого решения человека. Открытие и переход ничего
            не подтверждают.
          </p>
        </div>
      </div>
      {!apiKey.trim() ? (
        <div className="section-empty">
          <h2>Настройте подключение</h2>
          <p>Для доступа к событиям нужен ключ API.</p>
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
      ) : (
        <>
          <form
            className="history-filters"
            onSubmit={(e) => {
              e.preventDefault();
              try {
                periodDates(draft.period, draft.from, draft.to);
                onFilters(draft);
                setPage(1);
                setFormError("");
              } catch (p) {
                setFormError((p as Error).message);
              }
            }}
          >
            <PeriodFields
              value={draft.period}
              from={draft.from}
              to={draft.to}
              onChange={(v) => setDraft({ ...draft, ...v })}
            />
            <label>
              Тип события
              <select
                value={draft.category_id}
                onChange={(e) =>
                  setDraft({ ...draft, category_id: e.target.value })
                }
              >
                <option value="">Все типы</option>
                {options.types.map((t) => (
                  <option value={t.category_id} key={t.category_id}>
                    {t.type}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Метка
              <input
                list="queue-tags"
                value={draft.tag}
                maxLength={64}
                placeholder="Точная метка"
                onChange={(e) => setDraft({ ...draft, tag: e.target.value })}
              />
              <datalist id="queue-tags">
                {options.tags.map((t) => (
                  <option key={t} value={t} />
                ))}
              </datalist>
            </label>
            <button className="button primary">Применить</button>
            <button
              type="button"
              className="button secondary"
              onClick={() => {
                setDraft(defaultQueueFilters);
                onFilters(defaultQueueFilters);
                setPage(1);
                setFormError("");
              }}
            >
              Сбросить
            </button>
            {formError && <p role="alert">{formError}</p>}
          </form>
          {loading && (
            <p className="loading-state" role="status">
              <LoaderCircle size={20} className="spin" /> Загружаем события…
            </p>
          )}
          {error && (
            <div className="section-empty" role="alert">
              <p>{error}</p>
              <button className="button secondary" onClick={retry}>
                Повторить
              </button>
              <button className="text-button" onClick={onSettings}>
                Открыть настройки
              </button>
            </div>
          )}
          {data && (
            <>
              <p className="queue-progress" role="status">
                Рассмотрено {data.reviewed_events} из {data.total_events} · Не
                рассмотрено: {data.total}
              </p>
              {!data.items.length ? (
                <div className="section-empty">
                  <h2>Непроверенных событий нет</h2>
                  <p>
                    Все события рассмотрены или по выбранным фильтрам пока нет
                    результатов.
                  </p>
                </div>
              ) : (
                <ol className="queue-list">
                  {data.items.map((item) => (
                    <li key={item.event_id}>
                      <div className="queue-frame">
                        {item.frame ? (
                          <img
                            src={`data:image/jpeg;base64,${item.frame.image_base64}`}
                            alt={`Кадр события: ${item.type}`}
                          />
                        ) : (
                          <span>Кадр недоступен</span>
                        )}
                      </div>
                      <div className="queue-event-copy">
                        <strong>{item.type}</strong>
                        <p>{item.filename}</p>
                        <p className="tag-list">
                          {item.tags.length
                            ? item.tags.join(" · ")
                            : "Без меток"}
                        </p>
                        <small>
                          {new Date(item.created_at).toLocaleString("ru-RU")} ·{" "}
                          {timecode(item.timecode_sec)}
                          {item.mode === "demo" ? " · Демо" : ""}
                        </small>
                      </div>
                      <button
                        className="button secondary"
                        onClick={() => onOpen(item)}
                      >
                        Рассмотреть событие
                      </button>
                    </li>
                  ))}
                </ol>
              )}
              {data.total > 8 && (
                <div className="pagination">
                  <button
                    className="button secondary"
                    disabled={page === 1}
                    onClick={() => setPage((n) => n - 1)}
                  >
                    Назад
                  </button>
                  <span>
                    Страница {page} из {Math.ceil(data.total / 8)}
                  </span>
                  <button
                    className="button secondary"
                    disabled={page * 8 >= data.total}
                    onClick={() => setPage((n) => n + 1)}
                  >
                    Далее
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
