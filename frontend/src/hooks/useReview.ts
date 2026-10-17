import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, parseJob, request } from "../api";
import type { Job } from "../api";
export const ACTIVE_JOB_KEY = "cashier-guard-current-job";
export const API_KEY_STORAGE = "cashier-guard-key";
type SavedJob = { job_id: string; submitted_at: number };
type Phase =
  | "idle"
  | "uploading"
  | "restoring"
  | "processing"
  | "done"
  | "failed"
  | "interrupted";
function readSaved(): SavedJob | null {
  try {
    const item = JSON.parse(sessionStorage.getItem(ACTIVE_JOB_KEY) ?? "null");
    return item &&
      /^[a-zA-Z0-9_-]{1,100}$/.test(item.job_id) &&
      Number.isFinite(item.submitted_at)
      ? item
      : null;
  } catch {
    return null;
  }
}
function save(value: SavedJob | null) {
  try {
    if (value) sessionStorage.setItem(ACTIVE_JOB_KEY, JSON.stringify(value));
    else sessionStorage.removeItem(ACTIVE_JOB_KEY);
  } catch {
    /* Current tab works without storage. */
  }
}
export function readKey(): string {
  try {
    return sessionStorage.getItem(API_KEY_STORAGE) ?? "";
  } catch {
    return "";
  }
}
export function useReview(key: string) {
  const [saved, setSaved] = useState<SavedJob | null>(readSaved);
  const [job, setJob] = useState<Job | null>(null);
  const [phase, setPhase] = useState<Phase>(saved ? "restoring" : "idle");
  const [issue, setIssue] = useState<ApiError | null>(null);
  const [resumeVersion, setResumeVersion] = useState(0);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const sending = useRef(false);
  const keyRef = useRef(key);
  keyRef.current = key;
  useEffect(() => {
    try {
      sessionStorage.setItem(API_KEY_STORAGE, key);
    } catch {
      /* May be disabled. */
    }
  }, [key]);
  useEffect(() => {
    if (!saved) return;
    const token = ++generation.current;
    controller.current?.abort();
    const cancel = new AbortController();
    controller.current = cancel;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const valid = () => token === generation.current && !cancel.signal.aborted;
    const poll = async () => {
      try {
        if (!keyRef.current.trim())
          throw new ApiError(
            "auth",
            "Введите ключ доступа, чтобы восстановить проверку.",
          );
        const response = parseJob(
          await request<Job>(`/jobs/${saved.job_id}`, keyRef.current.trim(), {
            signal: cancel.signal,
            timeoutMs: 8_000,
            retries: 2,
          }),
          saved.job_id,
        );
        if (!valid()) return;
        setJob(response);
        if (response.status === "failed") {
          setPhase("failed");
          setIssue(
            new ApiError(
              "processing",
              response.error ??
                "Обработка не завершена. Результат не определён.",
            ),
          );
          return;
        }
        if (response.status === "done") {
          setPhase("done");
          setIssue(null);
          return;
        }
        const serverDeadline = response.deadline_at
          ? Date.parse(response.deadline_at)
          : NaN;
        const localDeadline = saved.submitted_at + 300_000;
        const deadline = Number.isFinite(serverDeadline)
          ? Math.min(serverDeadline, localDeadline)
          : localDeadline;
        if (Date.now() > deadline + 5_000)
          throw new ApiError(
            "timeout",
            "Время проверки истекло. Можно обновить статус или начать новую проверку.",
          );
        setPhase("processing");
        setIssue(null);
        timer = setTimeout(poll, 1000);
      } catch (error) {
        if (!valid()) return;
        const problem =
          error instanceof ApiError
            ? error
            : new ApiError("network", "Не удалось получить результат.");
        setIssue(problem);
        setPhase("interrupted");
        if (problem.kind === "not_found") {
          save(null);
          setSaved(null);
        }
      }
    };
    void poll();
    return () => {
      cancel.abort();
      clearTimeout(timer);
    };
  }, [saved, resumeVersion]);
  useEffect(
    () => () => {
      generation.current++;
      controller.current?.abort();
    },
    [],
  );
  const reset = useCallback(() => {
    generation.current++;
    controller.current?.abort();
    sending.current = false;
    setSaved(null);
    save(null);
    setJob(null);
    setIssue(null);
    setPhase("idle");
  }, []);
  const submit = useCallback(
    async (file: File, scenario: string) => {
      if (
        sending.current ||
        ["uploading", "processing", "restoring"].includes(phase)
      )
        return;
      if (!keyRef.current.trim()) {
        setIssue(new ApiError("auth", "Введите ключ доступа."));
        return;
      }
      sending.current = true;
      controller.current?.abort();
      const token = ++generation.current;
      const cancel = new AbortController();
      controller.current = cancel;
      setSaved(null);
      save(null);
      setJob(null);
      setIssue(null);
      setPhase("uploading");
      const submittedAt = Date.now();
      try {
        const body = new FormData();
        body.append("file", file);
        body.append("demo_scenario", scenario);
        const response = await request<{ job_id: string }>(
          "/analyze",
          keyRef.current.trim(),
          {
            method: "POST",
            body,
            signal: cancel.signal,
            timeoutMs: 65_000,
          },
        );
        if (token !== generation.current || cancel.signal.aborted) return;
        if (!response || !/^[a-zA-Z0-9_-]{1,100}$/.test(response.job_id))
          throw new ApiError(
            "protocol",
            "Сервис не вернул идентификатор проверки.",
          );
        const next = { job_id: response.job_id, submitted_at: submittedAt };
        sending.current = false;
        save(next);
        setSaved(next);
        setPhase("processing");
      } catch (error) {
        if (token !== generation.current || cancel.signal.aborted) return;
        setIssue(
          error instanceof ApiError
            ? error
            : new ApiError("network", "Не удалось загрузить видео."),
        );
        setPhase("interrupted");
      } finally {
        if (token === generation.current) sending.current = false;
      }
    },
    [phase],
  );
  const resume = useCallback(() => {
    if (saved) {
      setIssue(null);
      setPhase("restoring");
      setResumeVersion((value) => value + 1);
    }
  }, [saved]);
  return {
    job,
    phase,
    issue,
    submit,
    reset,
    resume,
    canResume: !!saved,
    busy: ["uploading", "processing", "restoring"].includes(phase),
    restoredId: saved?.job_id,
  };
}
