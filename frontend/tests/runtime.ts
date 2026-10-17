import { spawn, execFile, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import { mkdir, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

export const ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);
export const KEY = "cashier-guard-public-e2e-fixture-key";
export const BACKEND = "http://127.0.0.1:8010";
export const RUN = path.join(ROOT, "work/e2e", `run-${Date.now()}`);
export let STORAGE = path.join(RUN, "storage");
export const VIDEO = path.join(RUN, "synthetic-cashier-guard.mov");
export const LONG_VIDEO = path.join(
  RUN,
  `${"Synthetic_video_with_long_filename_".repeat(5)}.mov`,
);
let processHandle: ChildProcess | undefined;
let log = "";
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function startBackend() {
  if (processHandle) throw new Error("Test backend already running");
  try {
    await fetch(`${BACKEND}/api/v1/health`, {
      signal: AbortSignal.timeout(500),
    });
    throw new Error(
      "Port 8010 is occupied. E2E must not reuse or terminate another service.",
    );
  } catch (error) {
    if (error instanceof Error && error.message.includes("occupied"))
      throw error;
  }
  processHandle = spawn(
    path.join(ROOT, "backend/.venv/bin/python"),
    [
      "-m",
      "uvicorn",
      "app.main:app",
      "--host",
      "127.0.0.1",
      "--port",
      "8010",
      "--no-access-log",
    ],
    {
      cwd: path.join(ROOT, "backend"),
      env: {
        ...process.env,
        API_KEY: KEY,
        PIPELINE_MODE: "demo",
        STORAGE_DIR: STORAGE,
        RULES_PATH: path.join(ROOT, "data/rules.json"),
        JOB_TIMEOUT_SECONDS: "290",
        UPLOAD_TIMEOUT_SECONDS: "60",
        HISTORY_TTL_HOURS: "720",
        VIDEO_TTL_HOURS: "168",
        CLEANUP_INTERVAL_SECONDS: "0.2",
        PYTHONDONTWRITEBYTECODE: "1",
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  processHandle.stdout?.on("data", (chunk) => {
    log += chunk.toString();
  });
  processHandle.stderr?.on("data", (chunk) => {
    log += chunk.toString();
  });
  for (let attempt = 0; attempt < 60; attempt++) {
    if (processHandle.exitCode !== null)
      throw new Error(`Isolated backend exited: ${log}`);
    try {
      if ((await fetch(`${BACKEND}/api/v1/health`)).ok) return;
    } catch {
      /* Start-up only. */
    }
    await delay(100);
  }
  throw new Error(`Isolated backend did not start: ${log}`);
}

export async function stopBackend() {
  const child = processHandle;
  processHandle = undefined;
  if (!child || child.exitCode !== null) return;
  const exited = once(child, "exit");
  child.kill("SIGTERM");
  const forced = setTimeout(() => child.kill("SIGKILL"), 10_000);
  await exited;
  clearTimeout(forced);
  await writeFile(path.join(RUN, "backend.log"), log);
}

export async function restartBackend() {
  await stopBackend();
  await startBackend();
}

export async function prepareRuntime() {
  STORAGE = path.join(RUN, `storage-${Date.now()}`);
  await mkdir(RUN, { recursive: true });
  await promisify(execFile)("ffmpeg", [
    "-v",
    "error",
    "-f",
    "lavfi",
    "-i",
    "testsrc2=size=320x180:rate=30",
    "-t",
    "18.2",
    "-an",
    "-c:v",
    "libx264",
    "-preset",
    "ultrafast",
    "-pix_fmt",
    "yuv420p",
    "-movflags",
    "+faststart",
    "-y",
    VIDEO,
  ]);
  const { copyFile } = await import("node:fs/promises");
  await copyFile(VIDEO, LONG_VIDEO);
  await startBackend();
}

export async function jobFromApi(id: string) {
  const response = await fetch(`${BACKEND}/api/v1/jobs/${id}`, {
    headers: { "X-API-Key": KEY },
  });
  if (!response.ok) throw new Error(`Job GET failed: ${response.status}`);
  return response.json();
}

export async function uploads() {
  return (await readdir(STORAGE)).filter((name) => name.endsWith(".upload"));
}
