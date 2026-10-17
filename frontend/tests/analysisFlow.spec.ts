import { saveApiKey } from "./settingsFlow";
import { expect, test } from "@playwright/test";
import { KEY, VIDEO, prepareRuntime, stopBackend } from "./runtime";

test.beforeAll(async () => {
  await prepareRuntime();
});
test.afterAll(async () => {
  await stopBackend();
});

for (const width of [1440, 390]) {
  test(`demo backend permits local video selection but never analysis at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    let posts = 0;
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().endsWith("/analyze"))
        posts++;
    });
    await page.goto("/");
    await expect(
      page.getByText("Анализ видео пока недоступен", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /Перетащите видео сюда/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Проверить видео", exact: true }),
    ).toHaveCount(0);
    await expect(page.getByLabel("Тестовый сценарий")).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Запустить демопроверку", exact: true }),
    ).toHaveCount(0);
    await expect(page.locator(".form-actions")).toHaveCount(0);
    await saveApiKey(page, KEY);
    await page.getByLabel("Видео для проверки").setInputFiles(VIDEO);
    const submit = page.getByRole("button", {
      name: "Проверить видео",
      exact: true,
    });
    await expect(submit).toBeVisible();
    await expect(submit).toBeDisabled();
    await submit.evaluate((button: HTMLButtonElement) => button.click());
    await expect(page.locator(".completed-result")).toHaveCount(0);
    expect(posts).toBe(0);
    await page.getByRole("button", { name: "Убрать локальное видео" }).click();
    await expect(submit).toHaveCount(0);
    await expect(page.locator(".form-actions")).toHaveCount(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  });
}

test("live backend with unavailable models never submits a selected video", async ({
  page,
}) => {
  await page.route("**/api/v1/health", (route) =>
    route.fulfill({ json: { status: "ok", mode: "live", max_upload_mb: 100 } }),
  );
  await page.route("**/api/v1/ready", (route) =>
    route.fulfill({
      json: {
        ready: false,
        mode: "live",
        checks: { ml1: { ready: false, detail: "Модель не подключена" } },
      },
    }),
  );
  let posts = 0;
  page.on("request", (request) => {
    if (request.method() === "POST") posts++;
  });
  await page.goto("/");
  await expect(
    page.getByText("Анализ видео пока недоступен", { exact: true }),
  ).toBeVisible();
  await saveApiKey(page, KEY);
  await page.getByLabel("Видео для проверки").setInputFiles(VIDEO);
  await expect(
    page.getByRole("button", { name: "Проверить видео", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Повторить", exact: true }),
  ).toBeVisible();
  expect(posts).toBe(0);
  await expect(page.locator(".completed-result")).toHaveCount(0);
});
