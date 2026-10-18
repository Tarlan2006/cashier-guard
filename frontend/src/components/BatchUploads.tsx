import { useEffect, useState } from "react";
import { parseTags } from "../api";
import type { useBatch } from "../hooks/useBatch";
const labels = {
  waiting: "Ожидает",
  uploading: "Загружается",
  queued: "В очереди",
  processing: "Обрабатывается",
  done: "Завершена",
  error: "Ошибка",
  cancelled: "Отменена",
};
export function BatchUploads({
  batch,
  available,
  hasKey,
  onSettings,
  onOpen,
  focusJobId,
}: {
  focusJobId?: string;
  batch: ReturnType<typeof useBatch>;
  available: boolean;
  hasKey: boolean;
  onSettings: () => void;
  onOpen: (id: string) => void;
}) {
  const [tags, setTags] = useState(""),
    [error, setError] = useState("");
  const [expanded, setExpanded] = useState(true);
  useEffect(() => setExpanded(true), [batch.rows.length]);
  useEffect(() => {
    if (focusJobId) setExpanded(false);
  }, [focusJobId]);
  if (!batch.rows.length)
    return batch.error ? (
      <p className="form-error" role="alert">
        {batch.error}
      </p>
    ) : null;
  return (
    <section className="batch-uploads" aria-labelledby="batch-heading">
      <div className="panel-heading">
        <h2 id="batch-heading">Выбранные видео · {batch.rows.length} из 10</h2>
        <div className="batch-header-actions">
          <button
            className="text-button"
            aria-expanded={expanded}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? "Свернуть список" : "Показать список"}
          </button>
          <button
            className="text-button"
            disabled={batch.active}
            onClick={batch.clear}
          >
            Очистить список
          </button>
        </div>
      </div>
      <div hidden={!expanded}>
        <p className="review-note">
          Файлы отправляются по два. Обработку ограничивает действующая очередь
          сервера. Принятые задания сохраняются в истории.
        </p>
        <label>
          Метки для выбранных видео
          <input
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="Например: филиал, касса"
            maxLength={650}
          />
        </label>
        <ol className="batch-list">
          {batch.rows.map((row) => (
            <li key={row.id} data-status={row.status}>
              <div className="batch-file">
                <strong>{row.name}</strong>
                <small>
                  {(row.size / 1024 / 1024).toLocaleString("ru-RU", {
                    maximumFractionDigits: 2,
                  })}{" "}
                  МБ · {labels[row.status]}
                </small>
                {!!row.tags.length && <small>{row.tags.join(" · ")}</small>}
                {row.message && (
                  <p
                    className="review-note"
                    role={row.status === "error" ? "alert" : "status"}
                  >
                    {row.message}
                  </p>
                )}
              </div>
              <div className="batch-actions">
                {row.jobId && (
                  <button
                    className="button secondary"
                    onClick={() => onOpen(row.jobId!)}
                  >
                    Открыть проверку
                  </button>
                )}
                {!row.jobId && row.status === "waiting" && !row.send && (
                  <button
                    className="text-button"
                    onClick={() => batch.remove(row.id)}
                  >
                    Удалить файл
                  </button>
                )}
                {!row.jobId && row.status === "error" && (
                  <>
                    <label className="button secondary file-retry">
                      Выбрать файл повторно
                      <input
                        type="file"
                        aria-label={`Повторный файл ${row.name}`}
                        onChange={(e) => {
                          if (e.target.files?.[0])
                            batch.reattach(row.id, e.target.files[0]);
                        }}
                      />
                    </label>
                    <button
                      className="button secondary"
                      onClick={() => batch.retry(row.id)}
                    >
                      Повторить отправку
                    </button>
                    <button
                      className="text-button"
                      onClick={() => batch.remove(row.id)}
                    >
                      Удалить файл
                    </button>
                  </>
                )}
                {["waiting", "uploading", "queued", "processing"].includes(
                  row.status,
                ) && (
                  <button
                    className="button secondary"
                    disabled={row.cancelRequested}
                    onClick={() => void batch.cancel(row.id)}
                  >
                    {row.cancelRequested ? "Отменяем…" : "Отменить"}
                  </button>
                )}
              </div>
            </li>
          ))}
        </ol>
        {(batch.error || error) && (
          <p className="form-error" role="alert">
            {batch.error || error}
          </p>
        )}
        {!hasKey && (
          <p className="connection-prompt">
            Настройте подключение для проверки видео{" "}
            <a
              href="#settings"
              onClick={(e) => {
                e.preventDefault();
                onSettings();
              }}
            >
              Открыть настройки
            </a>
          </p>
        )}
        {!available && (
          <p className="review-note">Анализ видео пока недоступен</p>
        )}
        <div className="batch-toolbar">
          <button
            className="button primary"
            disabled={
              !available ||
              !hasKey ||
              !batch.rows.some((r) => r.status === "waiting" && !r.send)
            }
            onClick={() => {
              try {
                batch.start(parseTags(tags));
                setError("");
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            Запустить проверки
          </button>
          <button className="button secondary" onClick={batch.refresh}>
            Обновить статусы
          </button>
        </div>
      </div>
    </section>
  );
}
