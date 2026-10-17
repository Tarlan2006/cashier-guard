import { saveApiKey } from "./settingsFlow";
import { prepareAnalysisFixture } from "./analysisFixture";
import { execFile } from "node:child_process";
import { readdir } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { expect, test, type Page } from "@playwright/test";
import {
  KEY,
  RUN,
  STORAGE,
  jobFromApi,
  prepareRuntime,
  stopBackend,
} from "./runtime";

const AVI = path.join(RUN, "synthetic-with-audio.avi");
const WEBM = path.join(RUN, "synthetic-vp9.webm");
const OFFSET_MP4 = path.join(RUN, "synthetic-offset-five.mp4");
const exec = promisify(execFile);

test.beforeAll(async () => {
  await prepareRuntime();
  await exec(
    "ffmpeg",
    [
      "-v",
      "error",
      "-f",
      "lavfi",
      "-i",
      "testsrc2=size=320x180:rate=30",
      "-t",
      "1.3",
      "-an",
      "-c:v",
      "libx264",
      "-preset",
      "ultrafast",
      "-pix_fmt",
      "yuv420p",
      "-output_ts_offset",
      "5",
      "-y",
      OFFSET_MP4,
    ],
    { timeout: 20_000 },
  );
  await exec(
    "ffmpeg",
    [
      "-v",
      "error",
      "-f",
      "lavfi",
      "-i",
      "testsrc2=size=320x180:rate=24",
      "-f",
      "lavfi",
      "-i",
      "sine=frequency=440:sample_rate=44100",
      "-t",
      "6.25",
      "-c:v",
      "mpeg4",
      "-q:v",
      "4",
      "-c:a",
      "pcm_s16le",
      "-y",
      AVI,
    ],
    { timeout: 20_000 },
  );
  await exec(
    "ffmpeg",
    [
      "-v",
      "error",
      "-f",
      "lavfi",
      "-i",
      "testsrc2=size=320x180:rate=24",
      "-t",
      "6.25",
      "-an",
      "-c:v",
      "libvpx-vp9",
      "-deadline",
      "realtime",
      "-cpu-used",
      "8",
      "-b:v",
      "400k",
      "-y",
      WEBM,
    ],
    { timeout: 20_000 },
  );
});
test.afterAll(async () => {
  await stopBackend();
});

async function open(page: Page) {
  await prepareAnalysisFixture(page);
  await page.goto("/");
  await saveApiKey(page, KEY);
}

async function start(page: Page) {
  const response = page.waitForResponse(
    (item) =>
      item.url().endsWith("/api/v1/analyze") &&
      item.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Проверить видео", exact: true })
    .click();
  const submitted = await response;
  expect(submitted.status()).toBe(202);
  return (await submitted.json()).job_id as string;
}

async function complete(page: Page, id: string, filename: string) {
  await expect(
    page.getByRole("heading", { name: "Демо: Требует уточнения" }),
  ).toBeVisible({ timeout: 20_000 });
  const job = await jobFromApi(id);
  expect(job.status).toBe("done");
  expect(job.filename).toBe(filename);
  expect(job.duration_sec).toBeCloseTo(6.25, 1);
  expect(job.timings_sec.preparing).toBeGreaterThan(0);
  expect(job.violations[0].evidence_frames.length).toBeGreaterThan(0);
  for (const image of await page.locator(".evidence-frames img").all()) {
    await expect
      .poll(() =>
        image.evaluate(
          (node: HTMLImageElement) => node.complete && node.naturalWidth > 0,
        ),
      )
      .toBe(true);
  }
  await expect
    .poll(async () =>
      (await readdir(STORAGE)).filter(
        (name) => !name.startsWith("jobs.sqlite3") && name !== "videos",
      ),
    )
    .toEqual([]);
}

async function capture(page: Page, name: string) {
  await page.evaluate(async () => {
    if (document.activeElement instanceof HTMLElement)
      document.activeElement.blur();
    await document.fonts.ready;
    window.scrollTo(0, 0);
  });
  await page.screenshot({ path: path.join(RUN, name), fullPage: true });
}

test("AVI preview failure still permits analysis, normalized evidence and temporary-file cleanup", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await open(page);
  await page.getByLabel("Видео для проверки").setInputFiles(AVI);
  await expect(page.getByText(/Файл можно отправить на анализ/)).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Проверить видео", exact: true }),
  ).toBeEnabled();
  const id = await start(page);
  await complete(page, id, path.basename(AVI));
  await expect(page.getByLabel("Позиция в видео")).toHaveCount(0);
  await expect(page.locator(".event-detail .timecode")).toBeDisabled();
  const frame = page.getByRole("button", { name: /^Увеличить кадр 1,/ });
  await frame.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(frame).toBeFocused();
  await capture(page, "formats-avi-desktop.png");
});

test("WEBM upload works at 390px with all five formats visible and no horizontal overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  const formats = page.getByText("MOV, MP4, AVI, MKV и WEBM · до 100 МБ", {
    exact: true,
  });
  await expect(formats).toBeVisible();
  const bounds = await formats.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    ),
  ).toBe(true);
  await capture(page, "formats-mobile-upload.png");
  await page.getByLabel("Видео для проверки").setInputFiles(WEBM);
  const id = await start(page);
  await complete(page, id, path.basename(WEBM));
  await expect(page.getByLabel("Позиция в видео")).toBeVisible();
  await expect(page.locator(".event-detail .timecode")).toBeEnabled();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    ),
  ).toBe(true);
  await capture(page, "formats-webm-mobile.png");
});

test("nonzero source timestamps preserve event seek into the original browser video", async ({
  page,
}) => {
  await open(page);
  await page.getByLabel("Видео для проверки").setInputFiles(OFFSET_MP4);
  const id = await start(page);
  await expect(
    page.getByRole("heading", { name: "Демо: Требует уточнения" }),
  ).toBeVisible({ timeout: 20_000 });
  const job = await jobFromApi(id);
  expect(job.source_time_offset_sec).toBe(5);
  expect(job.duration_sec).toBeCloseTo(1.3, 2);
  const eventTime = job.violations[0].timecode_sec;
  const seek = page.locator(".event-detail .timecode");
  await expect(seek).toBeEnabled();
  await seek.click();
  await expect
    .poll(() =>
      page
        .locator("video")
        .evaluate((video: HTMLVideoElement) => video.currentTime),
    )
    .toBeCloseTo(eventTime + 5, 2);
  await expect
    .poll(async () =>
      Number(await page.getByLabel("Позиция в видео").inputValue()),
    )
    .toBeCloseTo(eventTime, 2);
  await page.getByRole("button", { name: "Посмотреть ±3 секунды" }).click();
  await expect(page.getByText("Фрагмент: 00:00.000 — 00:01.300")).toBeVisible();
  await expect
    .poll(() =>
      page.locator("video").evaluate((video: HTMLVideoElement) => video.paused),
    )
    .toBe(true);
  await capture(page, "formats-offset-timeline.png");
});
