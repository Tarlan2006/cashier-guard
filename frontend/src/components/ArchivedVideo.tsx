import { forwardRef, useEffect, useState } from "react";
import { FileVideo2, LoaderCircle } from "lucide-react";
import { request } from "../api";
import type { Job } from "../api";
import { VideoReview } from "./VideoReview";
import type { VideoHandle } from "./VideoReview";

export const ArchivedVideo = forwardRef<
  VideoHandle,
  {
    job: Job;
    apiKey: string;
    activeEvent: number;
    onSelect: (index: number) => void;
    onPreviewAvailabilityChange: (available: boolean) => void;
    onPick: () => void;
    disabled: boolean;
  }
>(function ArchivedVideo(
  {
    job,
    apiKey,
    activeEvent,
    onSelect,
    onPreviewAvailabilityChange,
    onPick,
    disabled,
  },
  ref,
) {
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  useEffect(() => {
    setFile(null);
    setDismissed(false);
    setError("");
    onPreviewAvailabilityChange(false);
    const controller = new AbortController();
    if (!job.video_available || !apiKey.trim()) {
      setLoading(false);
      return;
    }
    setLoading(true);
    void request<Blob>(
      `/jobs/${encodeURIComponent(job.job_id)}/video`,
      apiKey.trim(),
      {
        responseType: "blob",
        timeoutMs: 60_000,
        signal: controller.signal,
      },
    )
      .then((blob) => {
        if (!controller.signal.aborted)
          setFile(
            new File([blob], job.filename.replace(/\.[^.]+$/, "") + ".mp4", {
              type: "video/mp4",
            }),
          );
      })
      .catch((problem: Error) => {
        if (!controller.signal.aborted) setError(problem.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [
    job.job_id,
    job.video_available,
    apiKey,
    attempt,
    onPreviewAvailabilityChange,
    job.filename,
  ]);
  if (file && !dismissed)
    return (
      <VideoReview
        ref={ref}
        file={file}
        events={job.violations}
        activeEvent={activeEvent}
        normalizedDuration={job.duration_sec}
        sourceTimeOffset={0}
        onSelect={onSelect}
        onPreviewAvailabilityChange={onPreviewAvailabilityChange}
        disabled={false}
        onRemove={() => {
          setDismissed(true);
          onPreviewAvailabilityChange(false);
        }}
      />
    );
  return (
    <div className="restored-file">
      {loading ? (
        <LoaderCircle className="spin" size={26} />
      ) : (
        <FileVideo2 size={27} />
      )}
      <strong>{job.filename}</strong>
      <p>Проверка восстановлена.</p>
      <p role="status">
        {loading
          ? "Загружаем сохранённое видео…"
          : job.status === "processing"
            ? "Проверка ещё выполняется. Видеоархив появится после завершения."
            : error ||
              (!apiKey.trim()
                ? "Настройте подключение, чтобы открыть сохранённое видео."
                : job.video_available
                  ? "Видео сохранено в архиве."
                  : job.video_unavailable_reason === "expired"
                    ? "Срок хранения видео истёк. Результат и кадры остаются доступны до своего срока хранения."
                    : "Видеозапись недоступна в архиве. Результат и кадры доступны отдельно.")}
      </p>
      {!loading && job.video_available && apiKey.trim() && (
        <button
          className="button secondary"
          onClick={() => {
            if (file) setDismissed(false);
            else setAttempt((value) => value + 1);
          }}
        >
          {error ? "Повторить загрузку видео" : "Показать видео"}
        </button>
      )}
      {!loading && !job.video_available && (
        <button
          className="button secondary"
          disabled={disabled}
          onClick={onPick}
        >
          Выбрать файл для просмотра
        </button>
      )}
      {job.video_expires_at && (
        <small>
          Видео хранится до{" "}
          {new Date(job.video_expires_at).toLocaleString("ru-RU")}. Повторное
          открытие не запускает анализ.
        </small>
      )}
      {!job.video_available && (
        <small>
          Выбор исходного файла нужен только для просмотра и не запускает
          анализ.
        </small>
      )}
    </div>
  );
});
