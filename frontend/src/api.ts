export type Frame = { timestamp_sec: number; image_base64: string };
export type Rule = {
  id: string;
  title: string;
  document: string;
  section: string;
  url: string;
  is_demo?: boolean;
};
export type Violation = {
  type: string;
  timecode_sec: number;
  description: string;
  evidence_frames: Frame[];
  rule: Rule | null;
  rule_id?: string | null;
};
export type Job = {
  job_id: string;
  status: "processing" | "done" | "failed";
  stage: string;
  mode: "demo" | "live";
  filename: string;
  duration_sec: number | null;
  verdict: "violation" | "no_violation" | null;
  violations: Violation[];
  error: string | null;
  error_code?: string | null;
  size_bytes?: number;
  created_at?: string;
  deadline_at?: string | null;
  expires_at?: string | null;
  timings_sec?: Record<string, number>;
  demo_scenario?: string | null;
};
export type Health = {
  status: string;
  mode: "demo" | "live";
  max_upload_mb: number;
};
export type Readiness = {
  ready: boolean;
  mode: "demo" | "live";
  checks: Record<string, { ready: boolean; detail: string }>;
};
export type ErrorKind =
  | "auth"
  | "not_found"
  | "network"
  | "timeout"
  | "server"
  | "processing"
  | "protocol"
  | "validation";
export class ApiError extends Error {
  constructor(
    public kind: ErrorKind,
    message: string,
    public status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
export type RequestOptions = RequestInit & {
  timeoutMs?: number;
  retries?: number;
  retryDelayMs?: number;
};
function abortError() {
  return new DOMException("Запрос отменён", "AbortError");
}
async function delay(ms: number, signal?: AbortSignal | null) {
  if (signal?.aborted) throw abortError();
  await new Promise<void>((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
      reject(abortError());
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}
// Per-attempt timeout composes with cancellation. Never auto-retry a POST whose outcome is unknown.
export async function request<T>(
  path: string,
  key: string,
  options: RequestOptions = {},
): Promise<T> {
  const {
    timeoutMs = 8_000,
    retries = 0,
    retryDelayMs = 500,
    signal,
    ...init
  } = options;
  const maxRetries =
    (init.method ?? "GET").toUpperCase() === "GET" ? Math.min(retries, 3) : 0;
  for (let attempt = 0; ; attempt++) {
    if (signal?.aborted) throw abortError();
    const controller = new AbortController();
    let timedOut = false;
    const cancel = () => controller.abort();
    signal?.addEventListener("abort", cancel, { once: true });
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
    let failure: ApiError;
    try {
      const headers = new Headers(init.headers);
      if (key) headers.set("X-API-Key", key);
      const response = await fetch(`/api/v1${path}`, {
        ...init,
        headers,
        signal: controller.signal,
      });
      if (!response.ok) {
        const kind: ErrorKind = [401, 403].includes(response.status)
          ? "auth"
          : response.status === 404
            ? "not_found"
            : [408, 504].includes(response.status)
              ? "timeout"
              : response.status >= 500 || response.status === 429
                ? "server"
                : "validation";
        const defaults: Partial<Record<ErrorKind, string>> = {
          auth: "Ключ не принят. Исправьте его и продолжите проверку.",
          not_found:
            "Проверка не найдена или срок хранения истёк. Загрузите запись заново.",
          timeout:
            "Сервер не ответил вовремя. Можно повторно запросить результат.",
          server: "Сервис временно недоступен. Попробуйте позже.",
        };
        let message = defaults[kind] ?? `Запрос отклонён (${response.status}).`;
        try {
          const body = await response.json();
          if (typeof body.detail === "string" && body.detail.length < 600)
            message = body.detail;
          else if (typeof body.detail?.message === "string")
            message = body.detail.message;
        } catch {
          /* Keep status-based fallback for an invalid gateway response. */
        }
        throw new ApiError(kind, message, response.status);
      }
      try {
        return (await response.json()) as T;
      } catch (error) {
        if (controller.signal.aborted) throw error;
        throw new ApiError(
          "protocol",
          "Сервис вернул некорректный ответ. Результат не подтверждён.",
        );
      }
    } catch (error) {
      if (signal?.aborted) throw abortError();
      failure = timedOut
        ? new ApiError("timeout", "Превышено время ожидания ответа сервера.")
        : error instanceof ApiError
          ? error
          : new ApiError(
              "network",
              "Связь с сервером потеряна. Проверьте подключение.",
            );
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", cancel);
    }
    if (
      attempt >= maxRetries ||
      !["network", "timeout", "server"].includes(failure.kind)
    )
      throw failure;
    await delay(retryDelayMs * 2 ** attempt, signal);
  }
}
export function parseJob(value: Job, expectedId: string): Job {
  if (
    !value ||
    value.job_id !== expectedId ||
    !["processing", "done", "failed"].includes(value.status) ||
    !["demo", "live"].includes(value.mode) ||
    !Array.isArray(value.violations)
  )
    throw new ApiError(
      "protocol",
      "Ответ сервера не соответствует текущей проверке.",
    );
  if (
    value.status === "done" &&
    (!["violation", "no_violation"].includes(value.verdict ?? "") ||
      (value.verdict === "violation") !== value.violations.length > 0)
  )
    throw new ApiError(
      "protocol",
      "Сервис вернул несогласованный результат. Проверка не подтверждена.",
    );
  if (
    value.violations.some(
      (event) =>
        !event ||
        typeof event.type !== "string" ||
        typeof event.description !== "string" ||
        !Number.isFinite(event.timecode_sec) ||
        event.timecode_sec < 0 ||
        !Array.isArray(event.evidence_frames) ||
        event.evidence_frames.length < 1 ||
        event.evidence_frames.length > 3 ||
        event.evidence_frames.some(
          (frame) =>
            !frame ||
            !Number.isFinite(frame.timestamp_sec) ||
            frame.timestamp_sec < 0 ||
            typeof frame.image_base64 !== "string",
        ),
    )
  )
    throw new ApiError(
      "protocol",
      "В результате отсутствуют корректные события или доказательства.",
    );
  return value;
}
export function timecode(seconds: number): string {
  const millis = Math.max(
    0,
    Math.round((Number.isFinite(seconds) ? seconds : 0) * 1000),
  );
  return `${Math.floor(millis / 60_000)
    .toString()
    .padStart(2, "0")}:${Math.floor((millis / 1000) % 60)
    .toString()
    .padStart(2, "0")}.${(millis % 1000).toString().padStart(3, "0")}`;
}
export function scrollBehavior(): ScrollBehavior {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ? "auto"
    : "smooth";
}
