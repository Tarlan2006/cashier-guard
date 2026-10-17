export type Frame = { timestamp_sec: number; image_base64: string };
export type Assessment = "strong_evidence" | "needs_review";
export type Rule = {
  id: string;
  title: string;
  document: string;
  section: string;
  url: string;
  is_demo?: boolean;
};
export type HumanReview = {
  decision: "unreviewed" | "confirmed" | "rejected";
  comment: string;
  updated_at: string | null;
};
export type Violation = {
  event_id?: string | null;
  category_id?: string | null;
  human_review?: HumanReview | null;
  type: string;
  timecode_sec: number;
  description: string;
  evidence_frames: Frame[];
  rule: Rule | null;
  rule_id?: string | null;
  assessment?: Assessment | null;
  assessment_reason?: string | null;
};
export type Job = {
  job_id: string;
  status: "processing" | "done" | "failed";
  stage: string;
  mode: "demo" | "live";
  filename: string;
  duration_sec: number | null;
  source_time_offset_sec?: number | null;
  video_available?: boolean;
  video_expires_at?: string | null;
  video_size_bytes?: number | null;
  video_unavailable_reason?: "expired" | "missing" | "not_retained" | null;
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
  responseType?: "json" | "blob";
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
    responseType = "json",
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
          : [404, 410].includes(response.status)
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
        return (
          responseType === "blob"
            ? await response.blob()
            : await response.json()
        ) as T;
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
    typeof value.filename !== "string" ||
    typeof value.stage !== "string" ||
    (value.duration_sec !== null &&
      (!Number.isFinite(value.duration_sec) || value.duration_sec < 0)) ||
    (value.error !== null && typeof value.error !== "string") ||
    !Array.isArray(value.violations)
  )
    throw new ApiError(
      "protocol",
      "Ответ сервера не соответствует текущей проверке.",
    );
  if (
    value.status === "done" &&
    (!["violation", "no_violation"].includes(value.verdict ?? "") ||
      (value.verdict === "violation") !== value.violations.length > 0 ||
      value.stage !== "done" ||
      value.error !== null ||
      value.error_code != null)
  )
    throw new ApiError(
      "protocol",
      "Сервис вернул несогласованный результат. Проверка не подтверждена.",
    );
  if (
    value.status !== "done" &&
    (value.verdict !== null || value.violations.length > 0)
  )
    throw new ApiError(
      "protocol",
      "Незавершённая проверка не может содержать итоговый вердикт.",
    );
  if (
    value.violations.some(
      (event) =>
        !event ||
        !nonBlank(event.type) ||
        !nonBlank(event.description) ||
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
            !nonBlank(frame.image_base64),
        ),
    )
  )
    throw new ApiError(
      "protocol",
      "В результате отсутствуют корректные события или доказательства.",
    );
  for (const event of value.violations) {
    if (
      (event.assessment != null &&
        !["strong_evidence", "needs_review"].includes(event.assessment)) ||
      (event.assessment_reason != null && !nonBlank(event.assessment_reason)) ||
      (event.assessment === "strong_evidence" &&
        !nonBlank(event.assessment_reason))
    )
      throw new ApiError(
        "protocol",
        "Сервис передал некорректный уровень оценки или его объяснение. Проверка не завершена.",
      );
    if (
      event.assessment === "strong_evidence" &&
      value.mode === "live" &&
      (!isLiveRule(event.rule) ||
        event.rule_id !== event.rule?.id ||
        event.evidence_frames.some(
          (frame) => !isJpegEnvelope(frame.image_base64),
        ))
    )
      throw new ApiError(
        "protocol",
        "Для явных признаков нарушения не переданы корректное правило или кадры. Проверка не завершена.",
      );
  }
  return value;
}
function nonBlank(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}
function isLiveRule(rule: Rule | null): boolean {
  if (
    !rule ||
    rule.is_demo === true ||
    ![rule.id, rule.title, rule.document, rule.section].every(nonBlank) ||
    rule.id.startsWith("demo:") ||
    !nonBlank(rule.url) ||
    /\s/.test(rule.url)
  )
    return false;
  try {
    const source = new URL(rule.url);
    return (
      ["http:", "https:"].includes(source.protocol) &&
      !!source.hostname &&
      !source.username &&
      !source.password
    );
  } catch {
    return false;
  }
}
// The backend fully decodes and verifies JPEGs and resolves live rules against
// its checked catalog. This boundary check also rejects visibly broken payloads.
function isJpegEnvelope(value: string): boolean {
  if (
    value.length > 4_000_000 ||
    !/^[A-Za-z0-9+/]+={0,2}$/.test(value) ||
    value.length % 4 !== 0
  )
    return false;
  try {
    const bytes = atob(value);
    return (
      bytes.length >= 4 &&
      bytes.charCodeAt(0) === 0xff &&
      bytes.charCodeAt(1) === 0xd8 &&
      bytes.charCodeAt(bytes.length - 2) === 0xff &&
      bytes.charCodeAt(bytes.length - 1) === 0xd9
    );
  } catch {
    return false;
  }
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

export type HistoryItem = {
  job_id: string;
  filename: string;
  created_at: string;
  completed_at: string | null;
  expires_at: string;
  status: Job["status"];
  mode: Job["mode"];
  red_count: number;
  yellow_count: number;
  unreviewed_count: number;
  video_available: boolean;
  video_expires_at: string | null;
};
export type HistoryPage = {
  items: HistoryItem[];
  total: number;
  page: number;
  page_size: number;
};
export type Analytics = {
  successful_videos: number;
  videos_with_events: number;
  detected_events: number;
  confirmed_events: number;
  rejected_events: number;
  unreviewed_events: number;
  top_types: {
    category_id: string;
    type: string;
    detected: number;
    confirmed: number;
  }[];
  date_basis: "created_at";
};
