import {
  act,
  cleanup,
  render,
  renderHook,
  screen,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError, request, fetchJob, cancelJob } from "../api";
import type { Job } from "../api";
import { useBatch } from "../hooks/useBatch";
import { EventReview } from "./EventReview";
import { QueueNavigation, defaultQueueFilters } from "./ReviewQueue";
vi.mock("../api", async (original) => ({
  ...(await original<typeof import("../api")>()),
  request: vi.fn(),
  fetchJob: vi.fn(),
  cancelJob: vi.fn(),
}));
const transport = vi.mocked(request),
  getJob = vi.mocked(fetchJob),
  cancel = vi.mocked(cancelJob);
const job = (id: string, status: Job["status"] = "done"): Job => ({
  job_id: id,
  status,
  stage: status === "processing" ? "queued" : status,
  mode: "demo",
  filename: "fixture.mov",
  duration_sec: 12,
  verdict: status === "done" ? "no_violation" : null,
  violations: [],
  error: null,
});
function files(n: number) {
  return Array.from(
    { length: n },
    (_, i) => new File(["synthetic"], `Касса ${i}.mov`, { lastModified: 42 }),
  );
}
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}
async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}
beforeEach(() => {
  sessionStorage.clear();
  transport.mockReset();
  getJob.mockReset();
  cancel.mockReset();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  sessionStorage.clear();
});
it("limits selection to ten and sends only two uploads concurrently while retaining individual results", async () => {
  vi.useFakeTimers();
  const first = deferred<{ job_id: string }>(),
    second = deferred<{ job_id: string }>();
  transport.mockImplementation(async (path) => {
    if (path === "/analyze") {
      const n = transport.mock.calls.filter((c) => c[0] === "/analyze").length;
      if (n === 1) return first.promise;
      if (n === 2) return second.promise;
      return { job_id: "third-job" };
    }
    throw Error("unexpected");
  });
  getJob.mockImplementation(async (id) => job(id));
  const { result } = renderHook(() => useBatch("key", 100));
  act(() => result.current.add(files(11)));
  expect(result.current.rows).toHaveLength(0);
  expect(result.current.error).toContain("10");
  act(() => result.current.add(files(3)));
  act(() => result.current.start(["Филиал"]));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1500);
  });
  expect(transport.mock.calls.filter((c) => c[0] === "/analyze")).toHaveLength(
    2,
  );
  const keys = transport.mock.calls.map(
    (c) => (c[2]?.headers as Record<string, string>)["Idempotency-Key"],
  );
  expect(new Set(keys).size).toBe(2);
  await act(async () => {
    first.resolve({ job_id: "first-job" });
    await Promise.resolve();
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1500);
  });
  expect(transport.mock.calls.filter((c) => c[0] === "/analyze")).toHaveLength(
    3,
  );
  await act(async () => {
    second.resolve({ job_id: "second-job" });
    await Promise.resolve();
  });
  await flush();
  expect(result.current.rows.every((r) => r.status === "done")).toBe(true);
  expect(result.current.rows.every((r) => r.jobId)).toBe(true);
});
it("recovers a lost response by its persistent submission key without issuing a new POST", async () => {
  sessionStorage.setItem(
    "cashier-guard-batch",
    JSON.stringify([
      {
        id: "submission-key-0123456789",
        name: "Касса.mov",
        size: 9,
        modified: 42,
        status: "uploading",
        tags: ["Филиал"],
      },
    ]),
  );
  transport.mockResolvedValue(job("existing-job"));
  const { result } = renderHook(() => useBatch("key", 100));
  await flush();
  expect(result.current.rows[0]?.jobId).toBe("existing-job");
  expect(result.current.rows[0]?.status).toBe("done");
  expect(transport).toHaveBeenCalledWith(
    "/submissions/submission-key-0123456789",
    "key",
  );
  expect(transport.mock.calls.some((c) => c[2]?.method === "POST")).toBe(false);
});
it("isolates a failed upload and retries with its original idempotency key", async () => {
  vi.useFakeTimers();
  let posts = 0;
  transport.mockImplementation(async (path) => {
    if (path === "/analyze") {
      posts++;
      if (posts === 1) throw new ApiError("network", "lost");
      return { job_id: "job-" + posts };
    }
    throw new ApiError("not_found", "not yet");
  });
  getJob.mockImplementation(async (id) => job(id));
  const { result } = renderHook(() => useBatch("key", 100));
  act(() => result.current.add(files(2)));
  act(() => result.current.start([]));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1500);
  });
  await flush();
  const row = result.current.rows.find((r) => r.status === "error")!;
  expect(result.current.rows.some((r) => r.status === "done")).toBe(true);
  const originalKey = (
    transport.mock.calls.find((c) => c[0] === "/analyze")![2]
      ?.headers as Record<string, string>
  )["Idempotency-Key"];
  act(() => result.current.retry(row.id));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1500);
  });
  await flush();
  const last = transport.mock.calls.filter((c) => c[0] === "/analyze").at(-1)!;
  expect((last[2]?.headers as Record<string, string>)["Idempotency-Key"]).toBe(
    originalKey,
  );
});
it("cancels an accepted job on the backend and keeps its record", async () => {
  sessionStorage.setItem(
    "cashier-guard-batch",
    JSON.stringify([
      {
        id: "submission-key-0123456789",
        name: "Касса.mov",
        size: 9,
        modified: 42,
        status: "queued",
        tags: [],
        jobId: "queued-job",
      },
    ]),
  );
  getJob.mockResolvedValue(job("queued-job", "processing"));
  cancel.mockResolvedValue(job("queued-job", "cancelled"));
  const { result } = renderHook(() => useBatch("key", 100));
  await flush();
  await act(async () => {
    await result.current.cancel(result.current.rows[0]!.id);
  });
  expect(cancel).toHaveBeenCalledWith("queued-job", "key");
  expect(result.current.rows[0]?.status).toBe("cancelled");
  expect(result.current.rows[0]?.jobId).toBe("queued-job");
});
it("retains a reviewer draft after a save failure and when moving away and back", async () => {
  transport.mockRejectedValue(new ApiError("server", "Хранилище недоступно"));
  const event = {
    event_id: "event-1",
    type: "Fixture",
    timecode_sec: 1,
    description: "Test",
    evidence_frames: [],
    rule: null,
  };
  const props = { event, jobId: "job-1", apiKey: "key", onSaved: vi.fn() };
  const first = render(<EventReview {...props} />);
  await userEvent.selectOptions(
    screen.getByLabelText("Решение по событию"),
    "confirmed",
  );
  await userEvent.type(
    screen.getByLabelText(/Комментарий проверяющего/),
    "Комментарий сохранён в черновике",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Сохранить решение" }),
  );
  await screen.findByRole("alert");
  expect(props.onSaved).not.toHaveBeenCalled();
  first.unmount();
  render(<EventReview {...props} />);
  expect(
    (screen.getByLabelText(/Комментарий проверяющего/) as HTMLTextAreaElement)
      .value,
  ).toBe("Комментарий сохранён в черновике");
  expect(
    (screen.getByLabelText("Решение по событию") as HTMLSelectElement).value,
  ).toBe("confirmed");
});
it("moving to the next pending event only reads the queue and never changes a decision", async () => {
  const next = {
    job_id: "next-job",
    event_id: "next-event",
    category_id: "exact",
    type: "Exact",
    timecode_sec: 3,
    filename: "Next.mov",
    tags: [],
    created_at: "2026-10-18T00:00:00Z",
    mode: "live",
    frame: null,
  };
  transport.mockResolvedValue({
    items: [next],
    total: 5,
    total_events: 12,
    reviewed_events: 7,
    page: 1,
    page_size: 1,
  });
  const onOpen = vi.fn();
  render(
    <QueueNavigation
      apiKey="key"
      filters={defaultQueueFilters}
      eventId="current-event"
      revision={0}
      onOpen={onOpen}
    />,
  );
  await screen.findByText("Рассмотрено 7 из 12");
  await userEvent.click(
    screen.getByRole("button", { name: "Следующее непроверенное" }),
  );
  expect(onOpen).toHaveBeenCalledWith(next);
  expect(
    transport.mock.calls.every((c) => !c[2]?.method || c[2]?.method === "GET"),
  ).toBe(true);
});

it("refreshes an accepted job whose cancellation response was lost", async () => {
  sessionStorage.setItem(
    "cashier-guard-batch",
    JSON.stringify([
      {
        id: "submission-key-0123456789",
        name: "Касса.mov",
        size: 9,
        modified: 42,
        status: "error",
        uncertain: true,
        tags: [],
        jobId: "accepted-job",
      },
    ]),
  );
  getJob.mockResolvedValue(job("accepted-job", "cancelled"));
  const { result } = renderHook(() => useBatch("key", 100));
  await flush();
  expect(getJob).toHaveBeenCalledWith("accepted-job", "key");
  expect(result.current.rows[0]?.status).toBe("cancelled");
  expect(transport.mock.calls.some((c) => c[2]?.method === "POST")).toBe(false);
});
