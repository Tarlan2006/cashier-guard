import { saveApiKey } from "./settingsFlow";
import {
  prepareAnalysisFixture,
  selectAnalysisFixture,
} from "./analysisFixture";
import { expect, test, type Page } from "@playwright/test";
import {
  KEY,
  LONG_VIDEO,
  VIDEO,
  jobFromApi,
  prepareRuntime,
  restartBackend,
  stopBackend,
  uploads,
} from "./runtime";

const JOB_KEY = "cashier-guard-current-job";
const API_KEY_STORAGE = "cashier-guard-key";

test.beforeAll(async () => {
  await prepareRuntime();
});
test.afterAll(async () => {
  await stopBackend();
});

async function open(page: Page, key = KEY) {
  await prepareAnalysisFixture(page);
  await page.goto("/");
  await saveApiKey(page, key);
}

async function start(page: Page, scenario = "violation", file = VIDEO) {
  await page.getByLabel("Видео для проверки").setInputFiles(file);
  selectAnalysisFixture(page, scenario, file);
  const response = page.waitForResponse(
    (item) =>
      item.url().endsWith("/api/v1/analyze") &&
      item.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Проверить видео", exact: true })
    .click();
  const submission = await response;
  expect(submission.status()).toBe(202);
  return (await submission.json()).job_id as string;
}

async function done(page: Page) {
  await expect(page.getByRole("heading", { name: /^Демо:/ })).toBeVisible({
    timeout: 20_000,
  });
}

async function noOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    ),
  ).toBe(true);
}

test("refresh restores the current slow job and requires explicit local-file reattachment", async ({
  page,
}) => {
  await open(page);
  const id = await start(page, "slow");
  await expect(
    page.getByRole("heading", { name: "Проверяем видеозапись" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("Проверка восстановлена.", { exact: false }),
  ).toBeVisible();
  await expect(page.locator("video")).toHaveCount(0);
  await done(page);
  expect((await jobFromApi(id)).status).toBe("done");
  const posts: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST") posts.push(request.url());
  });
  await page
    .getByRole("button", { name: "Выбрать файл для просмотра" })
    .click();
  await page.getByLabel("Видео для проверки").setInputFiles(VIDEO);
  await expect(page.locator("video")).toBeVisible();
  expect(posts).toEqual([]);
  expect(await uploads()).toEqual([]);
});

test("completed results persist across a real backend restart; interrupted jobs fail explicitly", async ({
  page,
}) => {
  await open(page);
  const completedId = await start(page, "no_violation");
  await done(page);
  await restartBackend();
  await page.reload();
  await done(page);
  expect((await jobFromApi(completedId)).verdict).toBe("no_violation");
  await page
    .getByRole("button", { name: "Новая проверка", exact: true })
    .first()
    .click();
  const interruptedId = await start(page, "slow");
  await restartBackend();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Проверка не завершена" }),
  ).toBeVisible();
  await expect(page.getByText("Код: SERVER_RESTARTED")).toBeVisible();
  const failed = await jobFromApi(interruptedId);
  expect(failed.verdict).toBeNull();
  expect(failed.violations).toEqual([]);
  expect(await uploads()).toEqual([]);
  await expect(
    page.getByRole("button", { name: "Новая проверка", exact: true }).first(),
  ).toBeEnabled();
});

test("wrong POST key and restored GET key are editable; lost job clears saved identifier", async ({
  page,
}) => {
  await open(page, "wrong-key");
  await page.getByLabel("Видео для проверки").setInputFiles(VIDEO);
  await page
    .getByRole("button", { name: "Проверить видео", exact: true })
    .click();
  await expect(
    page.getByText("Нужно исправить ключ доступа", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "Открыть настройки", exact: true })
    .click();
  await expect(
    page.getByLabel("Ключ доступа к API", { exact: true }),
  ).toBeVisible();
  await saveApiKey(page, KEY);
  await page
    .getByRole("button", { name: "Проверить видео", exact: true })
    .click();
  await done(page);
  await page.evaluate(
    (key) => sessionStorage.setItem(key, "wrong-key"),
    API_KEY_STORAGE,
  );
  await page.reload();
  await expect(
    page.getByText("Нужно исправить ключ доступа", { exact: true }),
  ).toBeVisible();
  await saveApiKey(page, KEY);
  await page.getByRole("button", { name: "Продолжить с этим ключом" }).click();
  await done(page);
  await page.evaluate(
    (key) =>
      sessionStorage.setItem(
        key,
        JSON.stringify({ job_id: "missing-e2e-job", submitted_at: Date.now() }),
      ),
    JOB_KEY,
  );
  await page.reload();
  await expect(
    page.getByText("Проверка не найдена", { exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate((key) => sessionStorage.getItem(key), JOB_KEY),
  ).toBeNull();
});

test("three events preserve fractional seek and context; frame dialog supports keyboard and focus", async ({
  page,
}) => {
  await open(page);
  const id = await start(page, "multiple_events");
  await done(page);
  const job = await jobFromApi(id);
  await expect(
    page.getByLabel("Найденные события").getByRole("button"),
  ).toHaveCount(3);
  await expect(
    page.getByLabel("Отметки событий на шкале").getByRole("button"),
  ).toHaveCount(3);
  await page
    .getByLabel("Отметки событий на шкале")
    .getByRole("button")
    .nth(1)
    .click();
  await expect
    .poll(() =>
      page
        .locator("video")
        .evaluate((video: HTMLVideoElement) => video.currentTime),
    )
    .toBeCloseTo(job.violations[1].timecode_sec, 2);
  expect(job.violations[1].timecode_sec % 1).not.toBe(0);
  await page.getByRole("button", { name: "Посмотреть ±3 секунды" }).click();
  await expect(page.getByText("Фрагмент: 00:06.100 — 00:12.100")).toBeVisible();
  await expect
    .poll(
      () =>
        page
          .locator("video")
          .evaluate((video: HTMLVideoElement) => video.paused),
      { timeout: 9_000 },
    )
    .toBe(true);
  const frameButton = page.getByRole("button", { name: /^Увеличить кадр 1,/ });
  await frameButton.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect
    .poll(() =>
      page
        .getByRole("dialog")
        .evaluate((dialog) => dialog.contains(document.activeElement)),
    )
    .toBe(true);
  await page.getByRole("button", { name: "Увеличить 2×" }).click();
  await expect(page.getByRole("button", { name: "Уместить" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  for (let press = 0; press < 4; press++) {
    await page.keyboard.press("Tab");
    expect(
      await page
        .getByRole("dialog")
        .evaluate((dialog) => dialog.contains(document.activeElement)),
    ).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(frameButton).toBeFocused();
  await noOverflow(page);
});

test("three JPEG frames, long copy and fictional rule are readable on mobile", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  await start(page, "three_frames");
  await done(page);
  await expect(
    page.getByRole("button", { name: /^Увеличить кадр/ }),
  ).toHaveCount(3);
  for (const image of await page.locator(".evidence-frames img").all()) {
    expect(
      await image.evaluate(
        (node: HTMLImageElement) => node.complete && node.naturalWidth > 0,
      ),
    ).toBe(true);
  }
  await noOverflow(page);
  await page
    .getByRole("button", { name: "Новая проверка", exact: true })
    .first()
    .click();
  await start(page, "long_text", LONG_VIDEO);
  await done(page);
  await expect(
    page.getByText("Этот искусственный пример", { exact: false }),
  ).toBeVisible();
  await noOverflow(page);
  await page
    .getByRole("button", { name: "Новая проверка", exact: true })
    .first()
    .click();
  await start(page, "demo_rule");
  await done(page);
  await expect(
    page.getByText("Вымышленный источник · только для демонстрации", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Открыть источник" }),
  ).toHaveCount(0);
  await noOverflow(page);
});

test("ML error and invalid response show failure without a clean verdict", async ({
  page,
}) => {
  await open(page);
  for (const scenario of ["ml_error", "invalid_ml_response"]) {
    const id = await start(page, scenario);
    await expect(
      page.getByRole("heading", { name: "Проверка не завершена" }),
    ).toBeVisible();
    await expect(
      page.getByText("Вердикт не сформирован.", { exact: false }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Демо: Нарушений не обнаружено" }),
    ).toHaveCount(0);
    expect((await jobFromApi(id)).verdict).toBeNull();
    await expect(
      page.getByRole("button", { name: "Проверить видео", exact: true }),
    ).toBeEnabled();
    await page
      .getByRole("button", { name: "Новая проверка", exact: true })
      .first()
      .click();
  }
});

test("GET retries recover transient failure; exhausted retries unlock the form; double click sends one POST", async ({
  page,
}) => {
  await open(page);
  let gets = 0,
    posts = 0;
  await page.route("**/api/v1/jobs/*", (route) =>
    ++gets <= 2 ? route.abort("failed") : route.continue(),
  );
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/analyze"))
      posts++;
  });
  await page.getByLabel("Видео для проверки").setInputFiles(VIDEO);
  await page
    .getByRole("button", { name: "Проверить видео", exact: true })
    .evaluate((button: HTMLButtonElement) => {
      button.click();
      button.click();
    });
  await done(page);
  expect(gets).toBeGreaterThanOrEqual(3);
  expect(posts).toBe(1);
  await page.unroute("**/api/v1/jobs/*");
  let failures = 0;
  await page.route("**/api/v1/jobs/*", (route) => {
    failures++;
    return route.abort("failed");
  });
  await page.reload();
  await expect(
    page.getByText("Получение результата остановлено", { exact: true }),
  ).toBeVisible();
  expect(failures).toBe(3);
  await expect(
    page
      .getByRole("navigation", { name: "Разделы" })
      .getByRole("button", { name: "Настройки", exact: true }),
  ).toBeEnabled();
  await expect(
    page.getByRole("button", { name: "Новая проверка", exact: true }).first(),
  ).toBeEnabled();
  await page.unroute("**/api/v1/jobs/*");
  await page.getByRole("button", { name: "Обновить статус" }).click();
  await done(page);
});

test("hanging status requests time out within bounded attempts and permit recovery", async ({
  page,
}) => {
  await open(page);
  await start(page, "no_violation");
  await done(page);
  let attempts = 0;
  await page.route("**/api/v1/jobs/*", async (route) => {
    attempts++;
    // Slower than the client's eight-second deadline, but release interception
    // so teardown never leaves a permanently paused browser network request.
    await new Promise((resolve) => setTimeout(resolve, 9_000));
    await route
      .fulfill({
        status: 504,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Delayed E2E response" }),
      })
      .catch(() => {});
  });
  const started = Date.now();
  await page.reload();
  await expect(
    page.getByText("Время ожидания истекло", { exact: true }),
  ).toBeVisible({ timeout: 32_000 });
  expect(attempts).toBe(3);
  expect(Date.now() - started).toBeLessThan(32_000);
  await expect(
    page
      .getByRole("navigation", { name: "Разделы" })
      .getByRole("button", { name: "Настройки", exact: true }),
  ).toBeEnabled();
  await page.unroute("**/api/v1/jobs/*");
  await page.getByRole("button", { name: "Обновить статус" }).click();
  await done(page);
});

test("navigation cancels an old status request and its late response cannot replace a new screen", async ({
  page,
}) => {
  await open(page);
  const id = await start(page, "no_violation");
  await done(page);
  const oldResult = await jobFromApi(id);
  let release: (() => void) | undefined;
  let intercepted = false;
  await page.route("**/api/v1/jobs/*", async (route) => {
    intercepted = true;
    await new Promise<void>((resolve) => {
      release = resolve;
    });
    await route
      .fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(oldResult),
      })
      .catch(() => {});
  });
  await page.reload();
  await expect.poll(() => intercepted).toBe(true);
  await page.evaluate((key) => sessionStorage.removeItem(key), JOB_KEY);
  await page.reload();
  release?.();
  await expect(
    page.getByRole("heading", { name: "Всё важное — в одном месте" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: /^Демо:/ })).toHaveCount(0);
  expect(
    await page.evaluate((key) => sessionStorage.getItem(key), JOB_KEY),
  ).toBeNull();
});
