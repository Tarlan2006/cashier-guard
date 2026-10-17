import { mkdir } from "node:fs/promises";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { prepareAnalysisFixture } from "./analysisFixture";
import { openSettings } from "./settingsFlow";
import { KEY, RUN, VIDEO, prepareRuntime, stopBackend } from "./runtime";

const STORAGE_KEY = "cashier-guard-key";
const videoTab = (page: Page) =>
  page
    .getByRole("navigation", { name: "Разделы" })
    .getByRole("button", { name: "Проверка видео", exact: true });

test.beforeAll(async () => {
  await prepareRuntime();
});
test.afterAll(async () => {
  await stopBackend();
});

async function capture(page: Page, name: string) {
  await page.evaluate(async () => {
    if (document.activeElement instanceof HTMLElement)
      document.activeElement.blur();
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
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
    path: path.join(RUN, `settings-${name}.png`),
    fullPage: true,
    animations: "disabled",
  });
}

for (const width of [1440, 390]) {
  test(`settings save, mask, delete and preserve authorization after navigation at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    await prepareAnalysisFixture(page);
    await page.goto("/");
    await expect(
      page.getByLabel("Ключ доступа к API", { exact: true }),
    ).toHaveCount(0);
    await expect(page.locator("#key-hint")).toHaveCount(0);
    await page.getByLabel("Видео для проверки").setInputFiles(VIDEO);
    await expect
      .poll(() =>
        page
          .locator("video")
          .evaluate((video: HTMLVideoElement) => video.readyState),
      )
      .toBeGreaterThanOrEqual(3);
    await expect(
      page.getByText("Настройте подключение для проверки видео", {
        exact: true,
      }),
    ).toBeVisible();
    const submit = page.getByRole("button", {
      name: "Проверить видео",
      exact: true,
    });
    await expect(submit).toBeDisabled();
    await capture(page, `missing-key-${width}`);
    await page
      .getByRole("link", { name: "Открыть настройки", exact: true })
      .click();
    const field = page.getByLabel("Ключ доступа к API", { exact: true });
    await expect(field).toHaveAttribute("type", "password");
    await field.fill("unsaved-test-draft");
    expect(
      await page.evaluate((key) => sessionStorage.getItem(key), STORAGE_KEY),
    ).toBeNull();
    await videoTab(page).click();
    await expect(submit).toBeDisabled();
    await openSettings(page);
    await expect(field).toHaveValue("");
    await field.fill(`  ${KEY}  `);
    await page
      .getByRole("button", { name: "Показать ключ", exact: true })
      .click();
    await expect(field).toHaveAttribute("type", "text");
    await page
      .getByRole("button", { name: "Скрыть ключ", exact: true })
      .click();
    await expect(field).toHaveAttribute("type", "password");
    await page.getByRole("button", { name: "Сохранить", exact: true }).click();
    await expect(page.getByRole("status")).toHaveText("Ключ сохранён");
    expect(
      await page.evaluate((key) => sessionStorage.getItem(key), STORAGE_KEY),
    ).toBe(KEY);
    await capture(page, `saved-${width}`);
    for (const section of ["API", "Нормативы РК", "Архитектура", "Настройки"]) {
      await page
        .getByRole("navigation", { name: "Разделы" })
        .getByRole("button", { name: section, exact: true })
        .click();
    }
    await expect(field).toHaveValue(KEY);
    await videoTab(page).click();
    await expect(page.locator("video")).toBeVisible();
    await expect(
      page.getByLabel("Ключ доступа к API", { exact: true }),
    ).toHaveCount(0);
    await expect(submit).toBeEnabled();
    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/v1/analyze") &&
        response.request().method() === "POST",
    );
    await submit.click();
    const response = await responsePromise;
    expect(response.status()).toBe(202);
    expect(response.request().headers()["x-api-key"]).toBe(KEY);
    await expect(page.getByRole("heading", { name: /^Демо:/ })).toBeVisible();
    await openSettings(page);
    await page
      .getByRole("button", { name: "Удалить ключ", exact: true })
      .click();
    await expect(page.getByRole("status")).toHaveText("Ключ удалён");
    await expect(field).toHaveValue("");
    expect(
      await page.evaluate((key) => sessionStorage.getItem(key), STORAGE_KEY),
    ).toBeNull();
    await capture(page, `deleted-${width}`);
    await videoTab(page).click();
    await expect(page.locator("video")).toBeVisible();
    await expect(submit).toBeDisabled();
    await expect(
      page.getByText("Настройте подключение для проверки видео", {
        exact: true,
      }),
    ).toBeVisible();
    let posts = 0;
    page.on("request", (request) => {
      if (request.method() === "POST") posts++;
    });
    await submit.evaluate((button: HTMLButtonElement) => button.click());
    expect(posts).toBe(0);
    await page.reload();
    await openSettings(page);
    await expect(field).toHaveValue("");
    await field.fill(KEY);
    await page.getByRole("button", { name: "Сохранить", exact: true }).click();
    await page.reload();
    await openSettings(page);
    await expect(field).toHaveValue(KEY);
    await videoTab(page).click();
    await expect(
      page.getByRole("heading", {
        name: "Нужно исправить ключ доступа",
        exact: true,
      }),
    ).toHaveCount(0);
  });
}
