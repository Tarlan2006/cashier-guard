import { useEffect, useRef, useState } from "react";
import { request, ApiError } from "../api";
import type { HumanReview, Violation } from "../api";

export const decisionLabels = {
  unreviewed: "Не рассмотрено",
  confirmed: "Подтверждено",
  rejected: "Отклонено",
};
export function EventReview({
  event,
  jobId,
  apiKey,
  onSaved,
  onOpenSettings,
}: {
  event: Violation;
  jobId: string;
  apiKey: string;
  onSaved: (eventId: string, review: HumanReview) => void;
  onOpenSettings?: () => void;
}) {
  const saved = event.human_review;
  const [decision, setDecision] = useState<HumanReview["decision"]>(
    saved?.decision ?? "unreviewed",
  );
  const [comment, setComment] = useState(saved?.comment ?? "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  if (!event.event_id)
    return (
      <p className="review-note">
        Сохранение решений недоступно для этого ответа сервиса.
      </p>
    );
  const eventId = event.event_id;
  return (
    <form
      className="human-review"
      aria-label="Решение проверяющего"
      onSubmit={async (e) => {
        e.preventDefault();
        if (busy || !apiKey.trim()) return;
        const cancel = new AbortController();
        controller.current = cancel;
        setBusy(true);
        setMessage("");
        setError("");
        try {
          const result = await request<HumanReview>(
            `/jobs/${encodeURIComponent(jobId)}/events/${encodeURIComponent(eventId)}/review`,
            apiKey.trim(),
            {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ decision, comment }),
              signal: cancel.signal,
            },
          );
          if (
            !result ||
            !Object.hasOwn(decisionLabels, result.decision) ||
            typeof result.comment !== "string"
          )
            throw new ApiError("protocol", "Решение не подтверждено сервером.");
          if (!cancel.signal.aborted) {
            onSaved(eventId, result);
            setMessage("Решение сохранено");
          }
        } catch (problem) {
          if (!cancel.signal.aborted)
            setError(
              problem instanceof Error
                ? problem.message
                : "Не удалось сохранить решение.",
            );
        } finally {
          if (!cancel.signal.aborted) setBusy(false);
        }
      }}
    >
      <h4>Решение проверяющего</h4>
      <p className="review-note">
        Решение человека сохраняется отдельно от оценки и объяснения модели.
      </p>
      <label>
        Решение по событию
        <select
          value={decision}
          disabled={busy}
          onChange={(e) => {
            setDecision(e.target.value as HumanReview["decision"]);
            setMessage("");
          }}
        >
          {Object.entries(decisionLabels).map(([value, label]) => (
            <option value={value} key={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Комментарий проверяющего <span>(необязательно)</span>
        <textarea
          value={comment}
          rows={3}
          maxLength={4000}
          disabled={busy}
          onChange={(e) => {
            setComment(e.target.value);
            setMessage("");
          }}
        />
      </label>
      <button
        className="button secondary"
        type="submit"
        disabled={busy || !apiKey.trim()}
      >
        {busy ? "Сохраняем…" : "Сохранить решение"}
      </button>
      {!apiKey.trim() && onOpenSettings && (
        <a
          href="#settings"
          onClick={(e) => {
            e.preventDefault();
            onOpenSettings();
          }}
        >
          Открыть настройки
        </a>
      )}
      {saved?.updated_at && (
        <small>
          Изменено {new Date(saved.updated_at).toLocaleString("ru-RU")}
        </small>
      )}
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
