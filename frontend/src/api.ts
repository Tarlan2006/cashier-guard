export type Frame = { timestamp_sec: number; image_base64: string };
export type Rule = {
  id: string;
  title: string;
  document: string;
  section: string;
  url: string;
};
export type Violation = {
  type: string;
  timecode_sec: number;
  description: string;
  evidence_frames: Frame[];
  rule: Rule | null;
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
};
export type Health = {
  status: string;
  mode: "demo" | "live";
  max_upload_mb: number;
};

export async function request<T>(
  path: string,
  key: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers: { ...init.headers, ...(key ? { "X-API-Key": key } : {}) },
    signal: init.signal ?? AbortSignal.timeout(30_000),
  });
  if (!response.ok) {
    let message = `Ошибка сервера (${response.status}). Попробуйте ещё раз.`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      /* Keep a useful message for non-JSON gateway responses. */
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export function timecode(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0");
  return `${minutes}:${Math.floor(seconds % 60)
    .toString()
    .padStart(2, "0")}`;
}
