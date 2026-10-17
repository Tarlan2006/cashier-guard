import { execFile } from "node:child_process";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { expect, test, type Page } from "@playwright/test";
import {
  prepareAnalysisFixture,
  selectAnalysisFixture,
} from "./analysisFixture";
import { saveApiKey } from "./settingsFlow";
import {
  KEY,
  ROOT,
  RUN,
  STORAGE,
  VIDEO,
  prepareRuntime,
  restartBackend,
  stopBackend,
} from "./runtime";
const exec = promisify(execFile);
const nav = (page: Page, name: string) =>
  page
    .getByRole("navigation", { name: "Разделы" })
    .getByRole("button", { name, exact: true });
test.beforeAll(async () => {
  await prepareRuntime();
});
test.afterAll(async () => {
  await stopBackend();
});
async function shot(page: Page, name: string) {
  await page.evaluate(async () => {
    if (document.activeElement instanceof HTMLElement)
      document.activeElement.blur();
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
    await new Promise<void>((r) =>
      requestAnimationFrame(() => requestAnimationFrame(() => r())),
    );
  });
  expect((await page.locator(".topbar").boundingBox())?.y).toBe(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBe(true);
  await mkdir(RUN, { recursive: true });
  await page.screenshot({
    path: path.join(RUN, `history-${name}.png`),
    fullPage: true,
    animations: "disabled",
  });
}
async function seedAnalytics() {
  await exec(path.join(ROOT, "backend/.venv/bin/python"), [
    "-c",
    `
import sys,base64
from pathlib import Path
from datetime import datetime,timezone
from io import BytesIO
from PIL import Image
sys.path.insert(0,sys.argv[1])
from app.store import JobStore
from app.models import JobResponse,ReviewUpdate
store=JobStore(Path(sys.argv[2])/'jobs.sqlite3')
buf=BytesIO();Image.new('RGB',(32,24),'white').save(buf,'JPEG')
frame={'timestamp_sec':1,'image_base64':base64.b64encode(buf.getvalue()).decode()}
now=datetime.now(timezone.utc).isoformat()
for n in range(12):
 events=[]
 if n<2:
  events=[dict(type='Synthetic exact A',timecode_sec=1,description='Test fixture only',evidence_frames=[frame,frame,frame],assessment='needs_review')]
 if n==0:events.append(dict(type='Synthetic exact a',timecode_sec=2,description='Test fixture only',evidence_frames=[frame],assessment='needs_review'))
 status='done' if n<3 else 'failed'
 store.save(JobResponse(job_id='analytics-fixture-'+str(n),status=status,stage=status,mode='live',filename=('Синтетическая аналитика ' if n<3 else 'Неуспешная проверка ')+str(n)+'.mov',created_at=now,completed_at=now,expires_at='2099-01-01T00:00:00+00:00',duration_sec=12,verdict=('violation' if events else 'no_violation') if status=='done' else None,violations=events))
job=store.get('analytics-fixture-0')
store.update_review(job.job_id,job.violations[0].event_id,ReviewUpdate(decision='confirmed',comment='Synthetic reviewer fixture'))
store.update_review(job.job_id,job.violations[1].event_id,ReviewUpdate(decision='rejected'))
store.close()
`,
    path.join(ROOT, "backend"),
    STORAGE,
  ]);
}
test("four videos persist, reopen without ML, restore human decision, and analytics counts exact live categories", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await prepareAnalysisFixture(page);
  await page.goto("/");
  await saveApiKey(page, KEY);
  let posts = 0;
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/analyze")) posts++;
  });
  for (let n = 0; n < 4; n++) {
    if (n)
      await page
        .getByRole("button", { name: "Новая проверка", exact: true })
        .first()
        .click();
    await page.getByLabel("Видео для проверки").setInputFiles(VIDEO);
    selectAnalysisFixture(page, "mixed_assessments", VIDEO);
    await page
      .getByRole("button", { name: "Проверить видео", exact: true })
      .click();
    await expect(page.locator(".completed-result")).toBeVisible();
  }
  expect(posts).toBe(4);
  await nav(page, "История").click();
  await expect(page.locator(".history-item")).toHaveCount(4);
  await shot(page, "list-desktop");
  await page.setViewportSize({ width: 390, height: 844 });
  await shot(page, "list-mobile");
  await page
    .locator(".history-item")
    .last()
    .getByRole("button", { name: "Открыть проверку", exact: true })
    .click();
  await expect(page.locator(".completed-result")).toBeVisible();
  await expect(page.locator("video")).toBeVisible();
  await expect(page.locator(".evidence-heading .timecode")).toBeEnabled();
  await page.locator(".evidence-heading .timecode").click();
  await expect
    .poll(() =>
      page
        .locator("video")
        .evaluate((video: HTMLVideoElement) => video.currentTime),
    )
    .toBeCloseTo(3.64, 1);
  await page
    .getByLabel("Решение по событию", { exact: true })
    .selectOption("confirmed");
  await page
    .getByLabel("Комментарий проверяющего", { exact: false })
    .fill("Проверено по кадрам, тестовый комментарий");
  await page
    .getByRole("button", { name: "Сохранить решение", exact: true })
    .click();
  await expect(
    page.getByText("Решение сохранено", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Убрать локальное видео" }).click();
  await shot(page, "decision-mobile");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await shot(page, "decision-desktop");
  await page.setViewportSize({ width: 390, height: 844 });
  await restartBackend();
  await page.reload();
  await expect(page.locator(".completed-result")).toBeVisible();
  await expect(
    page.getByLabel("Решение по событию", { exact: true }),
  ).toHaveValue("confirmed");
  await expect(
    page.getByLabel("Комментарий проверяющего", { exact: false }),
  ).toHaveValue("Проверено по кадрам, тестовый комментарий");
  expect(posts).toBe(4);
  await nav(page, "История").click();
  await expect(page.locator(".history-item")).toHaveCount(4);
  await nav(page, "Аналитика").click();
  await expect(page.locator(".analytics-metrics dd").first()).toHaveText("0");
  await seedAnalytics();
  await nav(page, "История").click();
  await expect(
    page.getByText("Найдено проверок: 16", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".history-item")).toHaveCount(10);
  await page.getByRole("button", { name: "Далее", exact: true }).click();
  await expect(page.locator(".history-item")).toHaveCount(6);
  await page
    .getByLabel("Название видео", { exact: true })
    .fill("Синтетическая аналитика");
  await page.getByRole("button", { name: "Применить", exact: true }).click();
  await expect(page.locator(".history-item")).toHaveCount(3);
  await nav(page, "Аналитика").click();
  await expect(page.locator(".analytics-metrics dd")).toHaveText([
    "3",
    "2",
    "3",
    "1",
    "1",
    "1",
  ]);
  await expect(page.locator(".analytics-types li")).toHaveCount(2);
  await shot(page, "analytics-mobile");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await shot(page, "analytics-desktop");
  await page.getByRole("button", { name: /Synthetic exact A/ }).click();
  await expect(page.locator(".history-item")).toHaveCount(2);
  await expect(page.locator(".filter-summary")).toContainText(
    "Synthetic exact A",
  );
  await page
    .locator(".history-item")
    .filter({ hasText: "Синтетическая аналитика 0.mov" })
    .getByRole("button", { name: "Удалить", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Удалить проверку", exact: true })
    .click();
  await expect(page.locator(".history-item")).toHaveCount(1);
  await nav(page, "Аналитика").click();
  await expect(page.locator(".analytics-metrics dd")).toHaveText([
    "2",
    "1",
    "1",
    "0",
    "0",
    "1",
  ]);
  expect(posts).toBe(4);
  const unauthorized = await page.request.get("/api/v1/jobs");
  expect(unauthorized.status()).toBe(401);
});
