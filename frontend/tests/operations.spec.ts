import { copyFile, readFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import {
  KEY,
  RUN,
  VIDEO,
  prepareRuntime,
  restartBackend,
  stopBackend,
} from "./runtime";
import { prepareAnalysisFixture } from "./analysisFixture";
import { saveApiKey } from "./settingsFlow";
const nav = (page: Page, name: string) =>
  page
    .getByRole("navigation", { name: "Разделы" })
    .getByRole("button", { name, exact: true });
test.beforeAll(prepareRuntime);
test.afterAll(stopBackend);
async function shot(page: Page, name: string) {
  await page.evaluate(async () => {
    if (document.activeElement instanceof HTMLElement)
      document.activeElement.blur();
    window.scrollTo(0, 0);
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
  await page.screenshot({
    path: path.join(RUN, `operations-${name}.png`),
    fullPage: true,
    animations: "disabled",
  });
}
test("four uploads, real cancellation, tags, human queue, audited decisions, protected PDF and reload", async ({
  page,
}) => {
  test.setTimeout(100000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await prepareAnalysisFixture(page);
  const paths = await Promise.all(
    Array.from({ length: 4 }, async (_, i) => {
      const dest = path.join(RUN, `касса-${i + 1}.mov`);
      await copyFile(VIDEO, dest);
      return dest;
    }),
  );
  // Only the test backend generates explicitly marked demo fixtures; no override ships.
  await page.route("**/api/v1/analyze", async (route) => {
    const req = route.request(),
      name = req
        .postDataBuffer()!
        .toString("utf8")
        .match(/filename="([^"]+)"/)![1]!;
    const response = await page.request.post(req.url(), {
      headers: {
        "X-API-Key": req.headers()["x-api-key"]!,
        "Idempotency-Key": req.headers()["idempotency-key"]!,
      },
      multipart: {
        file: {
          name,
          mimeType: "video/quicktime",
          buffer: await readFile(path.join(RUN, name)),
        },
        tags: JSON.stringify(["Филиал А", "Касса"]),
        demo_scenario: "slow",
      },
    });
    await route.fulfill({ response });
  });
  let posts = 0;
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/analyze")) posts++;
    if (r.url().endsWith("/report.pdf") || r.url().endsWith("/video")) {
      expect(r.headers()["x-api-key"]).toBe(KEY);
      expect(r.url()).not.toContain(KEY);
    }
  });
  await page.goto("/");
  await saveApiKey(page, KEY);
  await page.getByLabel("Видео для проверки").setInputFiles(paths);
  await expect(page.locator(".batch-list li")).toHaveCount(4);
  await page.getByLabel("Метки для выбранных видео").fill("Филиал А, Касса");
  await shot(page, "batch-desktop");
  await page.setViewportSize({ width: 390, height: 844 });
  await shot(page, "batch-mobile");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page
    .getByRole("button", { name: "Запустить проверки", exact: true })
    .click();
  const fourth = page.locator(".batch-list li").nth(3);
  await expect(fourth).toContainText(/В очереди|Обрабатывается/, {
    timeout: 15000,
  });
  await fourth.getByRole("button", { name: "Отменить", exact: true }).click();
  await expect(fourth).toHaveAttribute("data-status", "cancelled");
  await expect(page.locator('.batch-list li[data-status="done"]')).toHaveCount(
    3,
    { timeout: 45000 },
  );
  expect(posts).toBe(4);
  await nav(page, "История").click();
  await page.getByLabel("Метка", { exact: true }).fill("Филиал А");
  await page.getByRole("button", { name: "Применить", exact: true }).click();
  await expect(page.locator(".history-item")).toHaveCount(4);
  await expect(
    page.locator(".history-item").filter({ hasText: "Отменено" }),
  ).toHaveCount(1);
  await nav(page, "На рассмотрении").click();
  await expect(page.locator(".queue-list li")).toHaveCount(3);
  await expect(page.locator(".queue-progress")).toContainText(
    "Рассмотрено 0 из 3",
  );
  await page.getByLabel("Метка", { exact: true }).fill("Филиал А");
  await page.getByRole("button", { name: "Применить", exact: true }).click();
  await expect(page.locator(".queue-list li")).toHaveCount(3);
  await shot(page, "queue-desktop");
  await page.setViewportSize({ width: 390, height: 844 });
  await shot(page, "queue-mobile");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page
    .locator(".queue-list li")
    .first()
    .getByRole("button", { name: "Рассмотреть событие" })
    .click();
  await expect(
    page.getByLabel("Решение по событию", { exact: true }),
  ).toHaveValue("unreviewed");
  await expect(page.locator(".evidence-heading .timecode")).toBeEnabled();
  let fail = true;
  await page.route("**/events/*/review", async (route) => {
    if (fail) {
      fail = false;
      await route.fulfill({
        status: 503,
        json: { detail: "Тестовая ошибка сохранения" },
      });
    } else await route.continue();
  });
  await page
    .getByLabel("Решение по событию", { exact: true })
    .selectOption("confirmed");
  await page.getByLabel(/Комментарий проверяющего/).fill("Проверено по кадрам");
  await page
    .getByRole("button", { name: "Сохранить решение", exact: true })
    .click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Тестовая ошибка сохранения" }),
  ).toBeVisible();
  await expect(page.getByLabel(/Комментарий проверяющего/)).toHaveValue(
    "Проверено по кадрам",
  );
  await page
    .getByRole("button", { name: "Следующее непроверенное", exact: true })
    .click();
  await expect(
    page.getByLabel("Решение по событию", { exact: true }),
  ).toHaveValue("unreviewed");
  await nav(page, "На рассмотрении").click();
  await expect(page.locator(".queue-progress")).toContainText(
    "Рассмотрено 0 из 3",
  );
  await page
    .locator(".queue-list li")
    .first()
    .getByRole("button", { name: "Рассмотреть событие" })
    .click();
  await expect(page.getByLabel(/Комментарий проверяющего/)).toHaveValue(
    "Проверено по кадрам",
  );
  await page
    .getByRole("button", { name: "Сохранить решение", exact: true })
    .click();
  await expect(
    page.getByText("Решение сохранено", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("complementary", {
      name: "Переход по непроверенным событиям",
    }),
  ).toContainText("Рассмотрено 1 из 3");
  await page
    .getByLabel("Решение по событию", { exact: true })
    .selectOption("rejected");
  await page
    .getByLabel(/Комментарий проверяющего/)
    .fill("После просмотра контекста отклонено");
  await page
    .getByRole("button", { name: "Сохранить решение", exact: true })
    .click();
  await expect(
    page.getByText("Решение сохранено", { exact: true }),
  ).toBeVisible();
  await page.getByText("Журнал решений", { exact: true }).click();
  await expect(page.locator(".decision-log li")).toHaveCount(2);
  await expect(page.locator(".decision-log li").first()).toContainText(
    "Подтверждено → Отклонено",
  );
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Скачать PDF", exact: true }).click();
  const pdf = await download;
  await mkdir(path.join(RUN, "reports"), { recursive: true });
  const pdfPath = path.join(RUN, "reports", "review.pdf");
  await pdf.saveAs(pdfPath);
  expect((await readFile(pdfPath)).subarray(0, 5).toString()).toBe("%PDF-");
  await page.getByRole("button", { name: "Убрать локальное видео" }).click();
  await shot(page, "decision-desktop");
  await page.setViewportSize({ width: 390, height: 844 });
  await shot(page, "decision-mobile");
  await restartBackend();
  await page.reload();
  await expect(
    page.getByLabel("Решение по событию", { exact: true }),
  ).toHaveValue("rejected");
  await expect(page.getByLabel(/Комментарий проверяющего/)).toHaveValue(
    "После просмотра контекста отклонено",
  );
  await nav(page, "История").click();
  await expect(page.locator(".history-item")).toHaveCount(4);
  await nav(page, "На рассмотрении").click();
  await expect(page.locator(".queue-list li")).toHaveCount(2);
  await expect(page.locator(".queue-progress")).toContainText(
    "Рассмотрено 1 из 3",
  );
  await nav(page, "Аналитика").click();
  await expect(page.locator(".analytics-metrics dd")).toHaveText([
    "0",
    "0",
    "0",
    "0",
    "0",
    "0",
  ]);
  expect(posts).toBe(4);
});
