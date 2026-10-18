import { useEffect, useState } from "react";
import { Download, LoaderCircle } from "lucide-react";
import { request, cancelJob, parseTags } from "../api";
import type { Job, ReviewLog } from "../api";
import { decisionLabels } from "./EventReview";

export function PdfButton({ job, apiKey }: { job: Job; apiKey: string }) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    <div className="pdf-download">
      <button
        className="text-button"
        disabled={busy || !apiKey.trim()}
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            const blob = await request<Blob>(
              `/jobs/${encodeURIComponent(job.job_id)}/report.pdf`,
              apiKey,
              { responseType: "blob", timeoutMs: 60000 },
            );
            if (blob.type !== "application/pdf")
              throw new Error("Сервис не вернул PDF-отчёт.");
            const url = URL.createObjectURL(blob),
              a = document.createElement("a");
            a.href = url;
            a.download = `cashier-guard-${job.job_id}.pdf`;
            a.click();
            setTimeout(() => URL.revokeObjectURL(url), 10000);
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? (
          <LoaderCircle size={16} className="spin" />
        ) : (
          <Download size={16} />
        )}{" "}
        {busy ? "Формируем PDF…" : "Скачать PDF"}
      </button>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
    </div>
  );
}
export function CancelButton({
  jobId,
  apiKey,
  onDone,
}: {
  jobId: string;
  apiKey: string;
  onDone: (job: Job) => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    <div className="cancel-control">
      <button
        className="button secondary"
        disabled={busy || !apiKey.trim()}
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            onDone(await cancelJob(jobId, apiKey));
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Отменяем…" : "Отменить"}
      </button>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
    </div>
  );
}
export function TagsEditor({
  job,
  apiKey,
  onSaved,
}: {
  job: Job;
  apiKey: string;
  onSaved: (tags: string[]) => void;
}) {
  const [text, setText] = useState((job.tags ?? []).join(", ")),
    [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    setText((job.tags ?? []).join(", "));
    setMessage("");
    setError("");
  }, [job.job_id]);
  return (
    <form
      className="tags-editor"
      onSubmit={async (e) => {
        e.preventDefault();
        setError("");
        setMessage("");
        try {
          const tags = parseTags(text);
          setBusy(true);
          const saved = await request<{ tags: string[] }>(
            `/jobs/${job.job_id}/tags`,
            apiKey,
            {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ tags }),
            },
          );
          onSaved(saved.tags);
          setMessage("Метки сохранены");
        } catch (p) {
          setError((p as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <label>
        Метки видео
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Например: филиал, касса"
          maxLength={650}
          disabled={busy}
        />
      </label>
      <small>
        До 10 меток через запятую. Используются в истории, очереди и PDF.
      </small>
      <button className="button secondary" disabled={busy || !apiKey.trim()}>
        {busy ? "Сохраняем…" : "Сохранить метки"}
      </button>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <p className="review-note" role="status">
        {message}
      </p>
    </form>
  );
}
export function DecisionLog({
  jobId,
  apiKey,
  revision,
}: {
  jobId: string;
  apiKey: string;
  revision: number;
}) {
  const [open, setOpen] = useState(false),
    [page, setPage] = useState(1),
    [data, setData] = useState<ReviewLog | null>(null),
    [error, setError] = useState(""),
    [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setData(null);
    setError("");
    void request<ReviewLog>(
      `/jobs/${jobId}/review-log?page=${page}&page_size=10`,
      apiKey,
      { signal: controller.signal },
    )
      .then((v) => {
        if (!controller.signal.aborted) setData(v);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [jobId, apiKey, page, open, revision, retry]);
  return (
    <details
      className="decision-log"
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary>Журнал решений</summary>
      <p className="review-note">
        История сохранённых изменений. Доступ общий по API-ключу; автор
        изменения не идентифицируется.
      </p>
      {open && (
        <>
          {error ? (
            <div role="alert">
              <p>{error}</p>
              <button
                className="button secondary"
                onClick={() => setRetry((n) => n + 1)}
              >
                Повторить
              </button>
            </div>
          ) : !data ? (
            <p role="status">Загружаем журнал…</p>
          ) : (
            <>
              {!data.items.length ? (
                <p>Изменений решений пока нет.</p>
              ) : (
                <ol>
                  {data.items.map((entry) => (
                    <li key={entry.id}>
                      <strong>{entry.type}</strong>
                      <time>
                        {new Date(entry.changed_at).toLocaleString("ru-RU")}
                      </time>
                      <p>
                        {entry.origin === "migration_snapshot"
                          ? "Состояние на момент миграции (ранние изменения неизвестны)"
                          : `${entry.previous ? decisionLabels[entry.previous.decision] : "Не рассмотрено"} → ${decisionLabels[entry.current.decision]}`}
                      </p>
                      <p>Комментарий: {entry.current.comment || "Не указан"}</p>
                      {entry.previous?.comment && (
                        <p className="review-note">
                          Ранее: {entry.previous.comment}
                        </p>
                      )}
                    </li>
                  ))}
                </ol>
              )}
              {data.total > 10 && (
                <div className="pagination">
                  <button
                    className="button secondary"
                    disabled={page === 1}
                    onClick={() => setPage((n) => n - 1)}
                  >
                    Назад
                  </button>
                  <span>Страница {page}</span>
                  <button
                    className="button secondary"
                    disabled={page * 10 >= data.total}
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
    </details>
  );
}
