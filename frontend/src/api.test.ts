import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, parseJob, request, timecode } from "./api";
import type { Job } from "./api";

const fetchMock = vi.fn<typeof fetch>();
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const pendingFetch: typeof fetch = (_url, init) =>
  new Promise((_resolve, reject) => {
    init?.signal?.addEventListener(
      "abort",
      () => reject(new DOMException("Aborted", "AbortError")),
      { once: true },
    );
  });

beforeEach(() => {
  vi.useFakeTimers();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("request lifecycle", () => {
  it("enforces its own timeout even when the caller provides a non-aborted signal", async () => {
    fetchMock.mockImplementation(pendingFetch);
    const caller = new AbortController();
    const outcome = request("/health", "", {
      signal: caller.signal,
      timeoutMs: 25,
    }).catch((error) => error);
    await vi.advanceTimersByTimeAsync(25);
    expect(await outcome).toMatchObject({ name: "ApiError", kind: "timeout" });
    expect(caller.signal.aborted).toBe(false);
    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);
  });

  it("aborts an in-flight request on caller cancellation without retrying", async () => {
    fetchMock.mockImplementation(pendingFetch);
    const caller = new AbortController();
    const outcome = request("/jobs/current", "private-test-key", {
      signal: caller.signal,
      retries: 3,
    }).catch((error) => error);
    caller.abort();
    expect(await outcome).toMatchObject({ name: "AbortError" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("never starts a request when its caller signal was already cancelled", async () => {
    const caller = new AbortController();
    caller.abort();
    await expect(
      request("/health", "", { signal: caller.signal }),
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("allows cancellation during exponential retry backoff", async () => {
    fetchMock.mockRejectedValue(new TypeError("connection reset"));
    const caller = new AbortController();
    const outcome = request("/health", "", {
      signal: caller.signal,
      retries: 3,
      retryDelayMs: 100,
    }).catch((error) => error);
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    caller.abort();
    expect(await outcome).toMatchObject({ name: "AbortError" });
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("recovers from a temporary network failure using a bounded GET retry", async () => {
    fetchMock
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValueOnce(response({ status: "ok" }));
    const outcome = request("/health", "", { retries: 2, retryDelayMs: 10 });
    await vi.advanceTimersByTimeAsync(10);
    expect(await outcome).toEqual({ status: "ok" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("caps retries at three even when asked for many more", async () => {
    fetchMock.mockRejectedValue(new TypeError("offline"));
    const outcome = request("/health", "", {
      retries: 100,
      retryDelayMs: 10,
    }).catch((error) => error);
    await vi.runAllTimersAsync();
    expect(await outcome).toMatchObject({ kind: "network" });
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("has a fresh timeout for each retry and terminates when all attempts time out", async () => {
    fetchMock.mockImplementation(pendingFetch);
    const outcome = request("/health", "", {
      timeoutMs: 20,
      retries: 2,
      retryDelayMs: 5,
    }).catch((error) => error);
    await vi.runAllTimersAsync();
    expect(await outcome).toMatchObject({ kind: "timeout" });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([
    [401, "auth"],
    [403, "auth"],
    [404, "not_found"],
    [422, "validation"],
  ] as const)("does not retry HTTP %s", async (status, kind) => {
    fetchMock.mockResolvedValue(
      response({ detail: "Server explanation" }, status),
    );
    await expect(
      request("/jobs/current", "private-test-key", { retries: 3 }),
    ).rejects.toMatchObject({ kind, status });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([429, 503, 504])(
    "retries a temporary HTTP %s and accepts recovery",
    async (status) => {
      fetchMock
        .mockResolvedValueOnce(
          response({ detail: "Temporarily unavailable" }, status),
        )
        .mockResolvedValueOnce(response({ ok: true }));
      const outcome = request("/health", "", { retries: 1, retryDelayMs: 5 });
      await vi.advanceTimersByTimeAsync(5);
      expect(await outcome).toEqual({ ok: true });
      expect(fetchMock).toHaveBeenCalledTimes(2);
    },
  );

  it("does not resend an upload after its network outcome becomes unknown", async () => {
    fetchMock.mockRejectedValue(new TypeError("connection reset"));
    await expect(
      request("/analyze", "private-test-key", {
        method: "POST",
        body: new FormData(),
        retries: 3,
      }),
    ).rejects.toMatchObject({ kind: "network" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("sends the key as a header without putting it in the URL", async () => {
    fetchMock.mockResolvedValue(response({ status: "ok" }));
    await request("/health", "private-test-key", {
      headers: { Accept: "application/json" },
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/health");
    const headers = new Headers(init?.headers);
    expect(headers.get("X-API-Key")).toBe("private-test-key");
    expect(headers.get("Accept")).toBe("application/json");
  });

  it("classifies malformed success JSON as a protocol error and does not retry it", async () => {
    fetchMock.mockResolvedValue(
      new Response("<html>gateway page</html>", { status: 200 }),
    );
    await expect(
      request("/jobs/current", "", { retries: 3 }),
    ).rejects.toMatchObject({ kind: "protocol" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

const cleanJob: Job = {
  job_id: "test-job",
  status: "done",
  stage: "done",
  mode: "demo",
  filename: "synthetic.mov",
  duration_sec: 12,
  verdict: "no_violation",
  violations: [],
  error: null,
};
const event = {
  type: "Demo observation",
  timecode_sec: 3.125,
  description: "Synthetic test event.",
  rule: null,
  evidence_frames: [
    {
      timestamp_sec: 3.125,
      image_base64: "test-jpeg-decode-is-server-responsibility",
    },
  ],
};
describe("result validation", () => {
  it("accepts a consistent completed response while preserving fractional timestamps", () => {
    const valid = {
      ...cleanJob,
      verdict: "violation" as const,
      violations: [event],
    };
    expect(parseJob(valid, "test-job").violations[0].timecode_sec).toBe(3.125);
  });

  it.each([
    ["an unrelated job", { ...cleanJob, job_id: "old-job" }],
    ["an unknown status", { ...cleanJob, status: "unknown" }],
    ["a missing verdict", { ...cleanJob, verdict: null }],
    ["a clear verdict with events", { ...cleanJob, violations: [event] }],
    [
      "a violation verdict without evidence",
      { ...cleanJob, verdict: "violation" },
    ],
    ["a missing events list", { ...cleanJob, violations: undefined }],
    [
      "negative timestamps",
      {
        ...cleanJob,
        verdict: "violation",
        violations: [{ ...event, timecode_sec: -0.1 }],
      },
    ],
    [
      "non-finite timestamps",
      {
        ...cleanJob,
        verdict: "violation",
        violations: [{ ...event, timecode_sec: Number.NaN }],
      },
    ],
    [
      "an event without frames",
      {
        ...cleanJob,
        verdict: "violation",
        violations: [{ ...event, evidence_frames: [] }],
      },
    ],
    [
      "an event with more than three frames",
      {
        ...cleanJob,
        verdict: "violation",
        violations: [
          {
            ...event,
            evidence_frames: Array(4).fill(event.evidence_frames[0]),
          },
        ],
      },
    ],
    ["a null event", { ...cleanJob, verdict: "violation", violations: [null] }],
    [
      "a null frame",
      {
        ...cleanJob,
        verdict: "violation",
        violations: [{ ...event, evidence_frames: [null] }],
      },
    ],
  ])(
    "rejects %s as an unconfirmed protocol result",
    (_description, invalid) => {
      expect(() => parseJob(invalid as Job, "test-job")).toThrow(ApiError);
      try {
        parseJob(invalid as Job, "test-job");
      } catch (error) {
        expect(error).toMatchObject({ kind: "protocol" });
      }
    },
  );

  it("retains failed processing as a failure, never manufacturing a clean verdict", () => {
    const failed: Job = {
      ...cleanJob,
      status: "failed",
      verdict: null,
      error: "ML service unavailable",
    };
    expect(parseJob(failed, "test-job")).toMatchObject({
      status: "failed",
      verdict: null,
    });
  });

  it.each([undefined, null, "needs_review", "strong_evidence"] as const)(
    "preserves assessment %s and its explanation without inventing fields",
    (assessment) => {
      const assessed = {
        ...event,
        ...(assessment === undefined ? {} : { assessment }),
        ...(assessment === "strong_evidence"
          ? { assessment_reason: "Демо: показаны явные признаки." }
          : {}),
      };
      const value: Job = {
        ...cleanJob,
        verdict: "violation",
        violations: [assessed],
      };
      expect(parseJob(value, "test-job")).toBe(value);
      expect(value.violations[0].assessment).toBe(assessment);
      if (assessment === undefined)
        expect(value.violations[0]).not.toHaveProperty("assessment");
    },
  );

  it.each([
    { assessment: "unknown", assessment_reason: "No valid level" },
    { assessment: 90, assessment_reason: "No confidence conversion" },
    { assessment: "strong_evidence" },
    { assessment: "strong_evidence", assessment_reason: null },
    { assessment: "strong_evidence", assessment_reason: "  " },
    { assessment: "needs_review", assessment_reason: "" },
    { assessment: "needs_review", assessment_reason: 90 },
  ])("rejects invalid assessment metadata %j", (metadata) => {
    expect(() =>
      parseJob(
        {
          ...cleanJob,
          verdict: "violation",
          violations: [{ ...event, ...metadata }],
        } as Job,
        "test-job",
      ),
    ).toThrow(ApiError);
  });

  it.each([
    { ...cleanJob, error: "Conversion failed" },
    { ...cleanJob, error_code: "ANALYSIS_TIMEOUT" },
    { ...cleanJob, status: "processing" },
    { ...cleanJob, status: "failed", error: "Timeout" },
    { ...cleanJob, duration_sec: Number.NaN },
    { ...cleanJob, duration_sec: -1 },
  ])("rejects a contradictory or corrupt completed result: %j", (invalid) => {
    expect(() => parseJob(invalid as Job, "test-job")).toThrow(ApiError);
  });
});

describe("live strong-evidence boundary", () => {
  // Real 2×2 JPEG. Full decoding and catalog provenance remain backend checks.
  const jpeg =
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAACAAIDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD5/ooooA//2Q==";
  const live: Job = {
    ...cleanJob,
    mode: "live",
    verdict: "violation",
    violations: [
      {
        ...event,
        assessment: "strong_evidence",
        assessment_reason: "Test-only evidence explanation.",
        rule_id: "test-only-rule",
        rule: {
          id: "test-only-rule",
          title: "Test fixture",
          document: "Test fixture document",
          section: "Test section",
          url: "https://example.test/test-only-rule",
          is_demo: false,
        },
        evidence_frames: [{ timestamp_sec: 3.125, image_base64: jpeg }],
      },
    ],
  };

  it("accepts a backend-resolved rule and correctly framed JPEG", () => {
    expect(parseJob(live, "test-job")).toBe(live);
  });

  it("rejects a demo rule ID even when its is_demo flag is false", () => {
    const rule = { ...live.violations[0].rule!, id: "demo:test-only-rule" };
    expect(() =>
      parseJob(
        {
          ...live,
          violations: [{ ...live.violations[0], rule_id: rule.id, rule }],
        },
        "test-job",
      ),
    ).toThrow(ApiError);
  });

  it("requires a matching rule_id for live strong evidence while preserving legacy yellow responses", () => {
    for (const rule_id of [undefined, null, "different-rule"]) {
      const mismatched: Job = {
        ...live,
        violations: [{ ...live.violations[0], rule_id }],
      };
      expect(() => parseJob(mismatched, "test-job")).toThrow(ApiError);
      const legacy: Job = {
        ...mismatched,
        violations: [{ ...mismatched.violations[0], assessment: undefined }],
      };
      expect(parseJob(legacy, "test-job")).toBe(legacy);
    }
  });

  it.each([
    null,
    { ...live.violations[0].rule!, is_demo: true },
    { ...live.violations[0].rule!, document: " " },
    { ...live.violations[0].rule!, url: "javascript:alert(1)" },
    { ...live.violations[0].rule!, url: "https://name:secret@example.test" },
  ])("rejects an absent, demo or invalid live rule: %j", (rule) => {
    expect(() =>
      parseJob(
        { ...live, violations: [{ ...live.violations[0], rule }] },
        "test-job",
      ),
    ).toThrow(ApiError);
  });

  it.each(["", "not-base64", "dGVzdA==", jpeg.slice(0, -8)])(
    "rejects an empty, invalid or incomplete JPEG envelope",
    (image_base64) => {
      expect(() =>
        parseJob(
          {
            ...live,
            violations: [
              {
                ...live.violations[0],
                evidence_frames: [{ timestamp_sec: 3.125, image_base64 }],
              },
            ],
          },
          "test-job",
        ),
      ).toThrow(ApiError);
    },
  );
});

describe("timecode", () => {
  it.each([
    [3.125, "00:03.125"],
    [61.007, "01:01.007"],
    [59.9996, "01:00.000"],
    [3600.5, "60:00.500"],
    [0, "00:00.000"],
  ])(
    "formats %s seconds without losing millisecond precision",
    (seconds, expected) => {
      expect(timecode(seconds as number)).toBe(expected);
    },
  );
});
