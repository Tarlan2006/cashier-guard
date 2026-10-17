import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, request } from "../api";
import type { Job, RequestOptions } from "../api";
import { ACTIVE_JOB_KEY, API_KEY_STORAGE, useReview } from "./useReview";

vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return { ...original, request: vi.fn() };
});
const requestMock = vi.mocked(request);
const video = new File(["synthetic-video-placeholder"], "synthetic.mov", {
  type: "video/quicktime",
});
const processing = (id = "job-current"): Job => ({
  job_id: id,
  status: "processing",
  stage: "analyzing",
  mode: "demo",
  filename: "synthetic.mov",
  duration_sec: 12,
  verdict: null,
  violations: [],
  error: null,
  deadline_at: new Date(Date.now() + 290_000).toISOString(),
});
const completed = (id = "job-current"): Job => ({
  ...processing(id),
  status: "done",
  stage: "done",
  verdict: "no_violation",
});
function saveJob(id = "job-current") {
  sessionStorage.setItem(
    ACTIVE_JOB_KEY,
    JSON.stringify({ job_id: id, submitted_at: Date.now() }),
  );
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}
async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  sessionStorage.clear();
  requestMock.mockReset();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  sessionStorage.clear();
});

describe("current review recovery", () => {
  it.each([null, "invalid-date", "2099-01-01T00:00:00Z"])(
    "enforces the local budget when the server deadline is %s",
    async (deadline) => {
      sessionStorage.setItem(
        ACTIVE_JOB_KEY,
        JSON.stringify({
          job_id: "job-current",
          submitted_at: Date.now() - 306_000,
        }),
      );
      requestMock.mockResolvedValue({ ...processing(), deadline_at: deadline });
      const { result } = renderHook(() => useReview("valid-key"));
      await flush();
      expect(result.current.phase).toBe("interrupted");
      expect(result.current.issue?.kind).toBe("timeout");
      expect(result.current.busy).toBe(false);
    },
  );

  it("restores a persisted current job after mounting and resumes polling to completion", async () => {
    saveJob();
    requestMock
      .mockResolvedValueOnce(processing())
      .mockResolvedValueOnce(completed());
    const { result } = renderHook(() => useReview("valid-key"));
    expect(result.current.phase).toBe("restoring");
    await flush();
    expect(requestMock).toHaveBeenNthCalledWith(
      1,
      "/jobs/job-current",
      "valid-key",
      expect.objectContaining({ retries: 2, timeoutMs: 8000 }),
    );
    expect(result.current.phase).toBe("processing");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.phase).toBe("done");
    expect(result.current.busy).toBe(false);
    expect(result.current.job?.verdict).toBe("no_violation");
    expect(
      requestMock.mock.calls.every(([path]) => path.startsWith("/jobs/")),
    ).toBe(true);
  });

  it("persists the upload job id and retrieves it after the hook remounts", async () => {
    requestMock
      .mockResolvedValueOnce({ job_id: "new-job" })
      .mockResolvedValueOnce(processing("new-job"));
    const first = renderHook(() => useReview("valid-key"));
    await act(async () => {
      await first.result.current.submit(video);
    });
    expect(
      JSON.parse(sessionStorage.getItem(ACTIVE_JOB_KEY) ?? "null"),
    ).toMatchObject({ job_id: "new-job" });
    expect(requestMock.mock.calls[0][2]).toMatchObject({ method: "POST" });
    const form = requestMock.mock.calls[0][2]?.body as FormData;
    expect(form.get("file")).toBe(video);
    expect(form.get("demo_scenario")).toBeNull();
    first.unmount();

    requestMock.mockResolvedValueOnce(completed("new-job"));
    const second = renderHook(() => useReview("valid-key"));
    await flush();
    expect(second.result.current.job?.job_id).toBe("new-job");
    expect(second.result.current.phase).toBe("done");
    expect(
      requestMock.mock.calls.filter(
        ([, , options]) => options?.method === "POST",
      ),
    ).toHaveLength(1);
  });

  it("ignores corrupt saved metadata and does not make an API request for it", async () => {
    sessionStorage.setItem(ACTIVE_JOB_KEY, "{broken-json");
    const { result } = renderHook(() => useReview("valid-key"));
    await flush();
    expect(result.current.phase).toBe("idle");
    expect(result.current.busy).toBe(false);
    expect(requestMock).not.toHaveBeenCalled();
  });

  it("unlocks on a rejected key, then resumes the same job with the corrected key", async () => {
    saveJob();
    requestMock
      .mockRejectedValueOnce(new ApiError("auth", "Key rejected", 401))
      .mockResolvedValueOnce(completed());
    const { result, rerender } = renderHook(({ apiKey }) => useReview(apiKey), {
      initialProps: { apiKey: "wrong-key" },
    });
    await flush();
    expect(result.current.phase).toBe("interrupted");
    expect(result.current.busy).toBe(false);
    expect(result.current.issue?.kind).toBe("auth");
    expect(result.current.canResume).toBe(true);

    rerender({ apiKey: "correct-key" });
    act(() => result.current.resume());
    await flush();
    expect(requestMock).toHaveBeenLastCalledWith(
      "/jobs/job-current",
      "correct-key",
      expect.any(Object),
    );
    expect(result.current.phase).toBe("done");
    expect(result.current.issue).toBeNull();
    expect(sessionStorage.getItem(API_KEY_STORAGE)).toBe("correct-key");
  });

  it("asks for a missing key without a request and can resume after one is entered", async () => {
    saveJob();
    const { result, rerender } = renderHook(({ apiKey }) => useReview(apiKey), {
      initialProps: { apiKey: "" },
    });
    await flush();
    expect(result.current.issue?.kind).toBe("auth");
    expect(result.current.busy).toBe(false);
    expect(requestMock).not.toHaveBeenCalled();
    requestMock.mockResolvedValueOnce(completed());
    rerender({ apiKey: "valid-key" });
    act(() => result.current.resume());
    await flush();
    expect(result.current.phase).toBe("done");
  });

  it("forgets a lost/expired job and permits another upload", async () => {
    saveJob();
    requestMock.mockRejectedValueOnce(
      new ApiError("not_found", "Expired", 404),
    );
    const { result } = renderHook(() => useReview("valid-key"));
    await flush();
    expect(result.current.issue?.kind).toBe("not_found");
    expect(result.current.busy).toBe(false);
    expect(result.current.canResume).toBe(false);
    expect(sessionStorage.getItem(ACTIVE_JOB_KEY)).toBeNull();

    requestMock
      .mockResolvedValueOnce({ job_id: "replacement-job" })
      .mockResolvedValueOnce(completed("replacement-job"));
    await act(async () => {
      await result.current.submit(video);
    });
    expect(result.current.job?.job_id).toBe("replacement-job");
    expect(result.current.phase).toBe("done");
  });

  it.each(["network", "timeout", "server"] as const)(
    "unlocks after exhausted %s errors without inventing a verdict",
    async (kind) => {
      saveJob();
      requestMock.mockRejectedValueOnce(
        new ApiError(kind, "Final request failure"),
      );
      const { result } = renderHook(() => useReview("valid-key"));
      await flush();
      expect(result.current.phase).toBe("interrupted");
      expect(result.current.busy).toBe(false);
      expect(result.current.issue?.kind).toBe(kind);
      expect(result.current.job?.verdict ?? null).toBeNull();
      expect(result.current.canResume).toBe(true);
    },
  );

  it("stops polling when the server deadline has elapsed", async () => {
    saveJob();
    requestMock.mockResolvedValueOnce({
      ...processing(),
      deadline_at: new Date(Date.now() - 10_000).toISOString(),
    });
    const { result } = renderHook(() => useReview("valid-key"));
    await flush();
    expect(result.current.phase).toBe("interrupted");
    expect(result.current.busy).toBe(false);
    expect(result.current.issue?.kind).toBe("timeout");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(requestMock).toHaveBeenCalledTimes(1);
  });

  it("shows a server/ML processing failure as failed and permits a new check", async () => {
    saveJob();
    requestMock.mockResolvedValueOnce({
      ...processing(),
      status: "failed",
      error: "Backend restarted",
      error_code: "SERVER_RESTARTED",
    });
    const { result } = renderHook(() => useReview("valid-key"));
    await flush();
    expect(result.current.phase).toBe("failed");
    expect(result.current.issue).toMatchObject({
      kind: "processing",
      message: "Backend restarted",
    });
    expect(result.current.busy).toBe(false);
    expect(result.current.job?.verdict).toBeNull();
  });

  it("rejects an inconsistent completed response instead of showing no violations", async () => {
    saveJob();
    requestMock.mockResolvedValueOnce({
      ...completed(),
      violations: [{ type: "unexpected event" }],
    });
    const { result } = renderHook(() => useReview("valid-key"));
    await flush();
    expect(result.current.issue?.kind).toBe("protocol");
    expect(result.current.phase).toBe("interrupted");
    expect(result.current.job).toBeNull();
  });

  it.each([undefined, "needs_review", "strong_evidence"] as const)(
    "restores a saved result with assessment %s and retains its exact export fields",
    async (assessment) => {
      saveJob();
      const response: Job = {
        ...completed(),
        verdict: "violation",
        violations: [
          {
            type: "Демо-событие",
            description: "Тест восстановления ответа.",
            timecode_sec: 3.125,
            evidence_frames: [
              { timestamp_sec: 3.125, image_base64: "fixture" },
            ],
            rule: null,
            ...(assessment === undefined
              ? {}
              : {
                  assessment,
                  assessment_reason: "Демо: объяснение сохранённого уровня.",
                }),
          },
        ],
      };
      requestMock.mockResolvedValueOnce(response);
      const { result } = renderHook(() => useReview("valid-key"));
      await flush();
      expect(result.current.phase).toBe("done");
      expect(result.current.issue).toBeNull();
      expect(JSON.stringify(result.current.job)).toBe(JSON.stringify(response));
      if (assessment === undefined)
        expect(result.current.job?.violations[0]).not.toHaveProperty(
          "assessment",
        );
    },
  );

  it.each([
    { assessment: "unknown", assessment_reason: "Unsupported level" },
    { assessment: "strong_evidence", assessment_reason: null },
  ])(
    "keeps a restored malformed assessment neutral and recoverable: %j",
    async (metadata) => {
      saveJob();
      requestMock.mockResolvedValueOnce({
        ...completed(),
        verdict: "violation",
        violations: [
          {
            type: "Corrupt event",
            description: "Malformed assessment metadata",
            timecode_sec: 1,
            evidence_frames: [{ timestamp_sec: 1, image_base64: "fixture" }],
            rule: null,
            ...metadata,
          },
        ],
      });
      const { result } = renderHook(() => useReview("valid-key"));
      await flush();
      expect(result.current.phase).toBe("interrupted");
      expect(result.current.issue?.kind).toBe("protocol");
      expect(result.current.job).toBeNull();
      expect(result.current.canResume).toBe(true);
    },
  );
});

describe("submission isolation and cancellation", () => {
  it("prevents duplicate uploads triggered before React rerenders", async () => {
    const upload = deferred<{ job_id: string }>();
    requestMock
      .mockReturnValueOnce(upload.promise)
      .mockResolvedValueOnce(completed("one-job"));
    const { result } = renderHook(() => useReview("valid-key"));
    let first!: Promise<void>;
    act(() => {
      first = result.current.submit(video);
      void result.current.submit(video);
    });
    expect(requestMock).toHaveBeenCalledTimes(1);
    expect(result.current.busy).toBe(true);
    await act(async () => {
      upload.resolve({ job_id: "one-job" });
      await first;
    });
    expect(
      requestMock.mock.calls.filter(([path]) => path === "/analyze"),
    ).toHaveLength(1);
    expect(result.current.phase).toBe("done");
  });

  it("unlocks after upload failure and does not persist a nonexistent job", async () => {
    requestMock.mockRejectedValueOnce(
      new ApiError("network", "Upload connection lost"),
    );
    const { result } = renderHook(() => useReview("valid-key"));
    await act(async () => {
      await result.current.submit(video);
    });
    expect(result.current.phase).toBe("interrupted");
    expect(result.current.busy).toBe(false);
    expect(result.current.canResume).toBe(false);
    expect(sessionStorage.getItem(ACTIVE_JOB_KEY)).toBeNull();
  });

  it("ignores a late status response after resetting the current check", async () => {
    saveJob();
    const oldRequest = deferred<Job>();
    requestMock.mockReturnValueOnce(oldRequest.promise);
    const { result } = renderHook(() => useReview("valid-key"));
    const options = requestMock.mock.calls[0][2] as RequestOptions;
    act(() => result.current.reset());
    expect(options.signal?.aborted).toBe(true);
    await act(async () => {
      oldRequest.resolve(completed());
      await oldRequest.promise;
    });
    expect(result.current.phase).toBe("idle");
    expect(result.current.job).toBeNull();
    expect(sessionStorage.getItem(ACTIVE_JOB_KEY)).toBeNull();
  });

  it("ignores an old upload response after reset and a newer upload", async () => {
    const oldUpload = deferred<{ job_id: string }>();
    requestMock.mockReturnValueOnce(oldUpload.promise);
    const { result } = renderHook(() => useReview("valid-key"));
    let first!: Promise<void>;
    act(() => {
      first = result.current.submit(video);
    });
    act(() => result.current.reset());
    requestMock
      .mockResolvedValueOnce({ job_id: "new-job" })
      .mockResolvedValueOnce(completed("new-job"));
    await act(async () => {
      await result.current.submit(video);
    });
    expect(result.current.job?.job_id).toBe("new-job");
    await act(async () => {
      oldUpload.resolve({ job_id: "old-job" });
      await first;
    });
    expect(result.current.job?.job_id).toBe("new-job");
    expect(result.current.phase).toBe("done");
    expect(
      JSON.parse(sessionStorage.getItem(ACTIVE_JOB_KEY) ?? "null").job_id,
    ).toBe("new-job");
  });

  it("aborts a polling request on unmount and suppresses late state changes", async () => {
    saveJob();
    const inFlight = deferred<Job>();
    requestMock.mockReturnValueOnce(inFlight.promise);
    const { unmount } = renderHook(() => useReview("valid-key"));
    const options = requestMock.mock.calls[0][2] as RequestOptions;
    expect(options.signal?.aborted).toBe(false);
    unmount();
    expect(options.signal?.aborted).toBe(true);
    await act(async () => {
      inFlight.resolve(processing());
      await inFlight.promise;
    });
    await vi.advanceTimersByTimeAsync(10_000);
    expect(requestMock).toHaveBeenCalledTimes(1);
  });

  it("aborts an upload on unmount without saving its late response", async () => {
    const inFlight = deferred<{ job_id: string }>();
    requestMock.mockReturnValueOnce(inFlight.promise);
    const { result, unmount } = renderHook(() => useReview("valid-key"));
    let submission!: Promise<void>;
    act(() => {
      submission = result.current.submit(video);
    });
    const options = requestMock.mock.calls[0][2] as RequestOptions;
    unmount();
    expect(options.signal?.aborted).toBe(true);
    await act(async () => {
      inFlight.resolve({ job_id: "cancelled-job" });
      await submission;
    });
    expect(sessionStorage.getItem(ACTIVE_JOB_KEY)).toBeNull();
  });
});
