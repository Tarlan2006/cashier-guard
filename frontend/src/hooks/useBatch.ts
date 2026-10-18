import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  cancelJob,
  fetchJob,
  parseJob,
  request,
  submitVideo,
} from "../api";
import type { Job } from "../api";
import { isSupportedVideoFilename } from "../videoFormats";
const STORAGE = "cashier-guard-batch";
export type BatchRow = {
  id: string;
  name: string;
  size: number;
  modified: number;
  status:
    | "waiting"
    | "uploading"
    | "queued"
    | "processing"
    | "done"
    | "error"
    | "cancelled";
  tags: string[];
  jobId?: string;
  message?: string;
  send?: boolean;
  cancelRequested?: boolean;
  uncertain?: boolean;
};
function readRows(): BatchRow[] {
  try {
    const rows = JSON.parse(sessionStorage.getItem(STORAGE) ?? "[]");
    return Array.isArray(rows)
      ? rows
          .filter(
            (r) =>
              typeof r.id === "string" &&
              /^[a-zA-Z0-9_-]{16,100}$/.test(r.id) &&
              typeof r.name === "string" &&
              Number.isFinite(r.size) &&
              Array.isArray(r.tags),
          )
          .slice(0, 10)
          .map((r) => ({
            ...r,
            send: false,
            ...(["waiting", "uploading"].includes(r.status)
              ? {
                  status: "error",
                  uncertain: true,
                  message:
                    "Файл не сохраняется браузером. Проверяем, было ли создано задание. Для повторной отправки выберите тот же файл.",
                }
              : {}),
          }))
      : [];
  } catch {
    return [];
  }
}
export function useBatch(apiKey: string, maxMB: number) {
  const [rows, setRows] = useState<BatchRow[]>(readRows),
    [error, setError] = useState("");
  const state = useRef(rows),
    files = useRef(new Map<string, File>()),
    sending = useRef(new Set<string>()),
    checking = useRef(new Set<string>()),
    mounted = useRef(true),
    key = useRef(apiKey);
  key.current = apiKey;
  function update(fn: (rows: BatchRow[]) => BatchRow[]) {
    const next = fn(state.current);
    state.current = next;
    if (mounted.current) setRows(next);
    try {
      sessionStorage.setItem(STORAGE, JSON.stringify(next));
    } catch {
      /* History remains the durable source for accepted jobs. */
    }
  }
  function patch(id: string, values: Partial<BatchRow>) {
    update((rows) => rows.map((r) => (r.id === id ? { ...r, ...values } : r)));
  }
  function apply(id: string, job: Job) {
    const current = state.current.find((row) => row.id === id);
    if (
      current &&
      ["done", "cancelled"].includes(current.status) &&
      job.status === "processing"
    )
      return;
    patch(id, {
      jobId: job.job_id,
      status:
        job.status === "failed"
          ? "error"
          : job.status === "processing"
            ? job.stage === "queued"
              ? "queued"
              : "processing"
            : job.status,
      message: job.error ?? "",
      uncertain: false,
      tags: job.tags ?? [],
    });
  }
  async function check(row: BatchRow) {
    if (checking.current.has(row.id) || !key.current.trim()) return;
    checking.current.add(row.id);
    try {
      const job = row.jobId
        ? await fetchJob(row.jobId, key.current)
        : await request<Job>(`/submissions/${row.id}`, key.current);
      parseJob(job, job.job_id);
      apply(row.id, job);
      if (row.cancelRequested && job.status === "processing")
        apply(row.id, await cancelJob(job.job_id, key.current));
    } catch (e) {
      if (row.jobId) patch(row.id, { message: (e as Error).message });
      else if (e instanceof ApiError && e.kind === "not_found")
        patch(row.id, {
          message:
            "Отправка пока не подтверждена. Выберите тот же файл и повторите отправку с прежним ключом.",
        });
      else patch(row.id, { message: (e as Error).message });
    } finally {
      checking.current.delete(row.id);
    }
  }
  useEffect(() => {
    mounted.current = true;
    const tick = () => {
      if (!key.current.trim()) return;
      for (const row of state.current) {
        if (
          (row.jobId && ["queued", "processing"].includes(row.status)) ||
          row.uncertain
        )
          void check(row);
        if (
          row.status !== "waiting" ||
          !row.send ||
          sending.current.size >= 2 ||
          !files.current.has(row.id) ||
          sending.current.has(row.id)
        )
          continue;
        sending.current.add(row.id);
        patch(row.id, { status: "uploading", message: "", send: false });
        void submitVideo(
          files.current.get(row.id)!,
          key.current,
          { requestKey: row.id, tags: row.tags },
          request,
        )
          .then(async (result) => {
            patch(row.id, {
              jobId: result.job_id,
              status: "queued",
              uncertain: false,
            });
            const current = state.current.find((r) => r.id === row.id);
            if (current?.cancelRequested)
              apply(row.id, await cancelJob(result.job_id, key.current));
            else await check({ ...row, jobId: result.job_id });
          })
          .catch((e) => {
            patch(row.id, {
              status: "error",
              uncertain: true,
              message: (e as Error).message,
            });
          })
          .finally(() => sending.current.delete(row.id));
      }
    };
    tick();
    const interval = setInterval(tick, 1500);
    return () => {
      mounted.current = false;
      clearInterval(interval);
    };
  }, []);
  function add(selected: File[]) {
    setError("");
    if (state.current.length + selected.length > 10) {
      setError(
        "В списке может быть не более 10 видео. Удалите файлы или очистите завершённый список.",
      );
      return;
    }
    const added: BatchRow[] = [];
    for (const file of selected) {
      if (
        state.current.some(
          (r) =>
            r.name === file.name &&
            r.size === file.size &&
            r.modified === file.lastModified,
        ) ||
        added.some((r) => r.name === file.name && r.size === file.size)
      ) {
        setError("Повторно выбранный файл уже есть в списке.");
        continue;
      }
      const id = crypto.randomUUID();
      files.current.set(id, file);
      const issue = !isSupportedVideoFilename(file.name)
        ? "Неподдерживаемый формат."
        : !file.size
          ? "Файл пуст."
          : file.size > maxMB * 1024 * 1024
            ? `Размер превышает ${maxMB} МБ.`
            : "";
      added.push({
        id,
        name: file.name,
        size: file.size,
        modified: file.lastModified,
        status: issue ? "error" : "waiting",
        tags: [],
        message: issue,
      });
    }
    update((rows) => [...rows, ...added]);
  }
  return {
    rows,
    error,
    add,
    active: rows.some(
      (r) =>
        ["uploading", "queued", "processing"].includes(r.status) ||
        (r.status === "waiting" && r.send),
    ),
    start: (tags: string[]) =>
      update((rows) =>
        rows.map((r) =>
          r.status === "waiting" ? { ...r, tags, send: true } : r,
        ),
      ),
    remove: (id: string) => {
      if (sending.current.has(id)) return;
      files.current.delete(id);
      update((rows) => rows.filter((r) => r.id !== id));
    },
    clear: () => {
      if (
        state.current.some((r) =>
          ["uploading", "queued", "processing"].includes(r.status),
        )
      )
        return;
      files.current.clear();
      update(() => []);
    },
    retry: (id: string) => {
      if (files.current.has(id))
        patch(id, { status: "waiting", send: true, message: "" });
      else
        patch(id, { message: "Выберите тот же файл для повторной отправки." });
    },
    reattach: (id: string, file: File) => {
      const row = state.current.find((r) => r.id === id);
      if (!row || file.name !== row.name || file.size !== row.size) {
        setError("Для повтора нужен файл с тем же названием и размером.");
        return;
      }
      files.current.set(id, file);
      patch(id, {
        message: "Файл выбран. Повтор использует прежний ключ отправки.",
      });
    },
    cancel: async (id: string) => {
      const row = state.current.find((r) => r.id === id);
      if (!row) return;
      patch(id, { cancelRequested: true });
      if (row.jobId) {
        try {
          apply(id, await cancelJob(row.jobId, key.current));
        } catch (e) {
          patch(id, { message: (e as Error).message, cancelRequested: false });
        }
      } else if (row.status === "uploading")
        patch(id, {
          message:
            "Отменяем после завершения загрузки на сервер. Другие проверки продолжатся.",
        });
      else if (row.uncertain) {
        await check({ ...row, cancelRequested: true });
      } else
        patch(id, {
          status: "cancelled",
          send: false,
          message: "Файл отменён до отправки.",
        });
    },
    refresh: () => {
      for (const row of state.current)
        if (row.jobId || row.uncertain) void check(row);
    },
  };
}
