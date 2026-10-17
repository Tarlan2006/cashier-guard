import { saveApiKey } from "./settingsFlow";
import {
  prepareAnalysisFixture,
  selectAnalysisFixture,
} from "./analysisFixture";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import {
  KEY,
  RUN,
  VIDEO,
  jobFromApi,
  prepareRuntime,
  restartBackend,
  stopBackend,
} from "./runtime";

test.beforeAll(async () => {
  await prepareRuntime();
});
test.afterAll(async () => {
  await stopBackend();
});

async function open(page: Page) {
  await prepareAnalysisFixture(page);
  await page.goto("/");
  await saveApiKey(page, KEY);
}
async function start(page: Page, scenario: string) {
  await page.getByLabel("Видео для проверки").setInputFiles(VIDEO);
  selectAnalysisFixture(page, scenario, VIDEO);
  const response = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/v1/analyze") && r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Проверить видео", exact: true })
    .click();
  const submitted = await response;
  expect(submitted.status()).toBe(202);
  const id = (await submitted.json()).job_id;
  await expect(page.locator(".completed-result")).toBeVisible({
    timeout: 20_000,
  });
  return id as string;
}
async function exported(page: Page) {
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Скачать JSON" }).click();
  const file = await download;
  const target = path.join(RUN, file.suggestedFilename());
  await file.saveAs(target);
  return JSON.parse(await readFile(target, "utf8"));
}
async function noOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBe(true);
}
async function contrast(page: Page) {
  const pairs = await page
    .locator(
      ".verdict, .assessment-badge, .timeline-markers button, .timeline-events button",
    )
    .evaluateAll((elements) =>
      elements.map((node) => {
        const css = getComputedStyle(node);
        return [css.color, css.backgroundColor];
      }),
    );
  const luminance = (rgb: string) => {
    const components = rgb
      .match(/[\d.]+/g)!
      .slice(0, 3)
      .map((n) => {
        const v = Number(n) / 255;
        return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
      });
    return (
      components[0] * 0.2126 + components[1] * 0.7152 + components[2] * 0.0722
    );
  };
  for (const [foreground, background] of pairs) {
    const a = luminance(foreground),
      b = luminance(background);
    expect(
      (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05),
      `${foreground} on ${background}`,
    ).toBeGreaterThanOrEqual(4.5);
  }
}

for (const [scenario, level, title, strong, review] of [
  ["no_violation", "clear", "Нарушений не обнаружено", 0, 0],
  ["strong_evidence", "strong_evidence", "Явные признаки нарушения", 1, 0],
  ["needs_review", "needs_review", "Требует уточнения", 0, 1],
] as const) {
  test(`${scenario}: real demo produces the labelled level and correct counts`, async ({
    page,
  }) => {
    await open(page);
    const id = await start(page, scenario);
    await expect(
      page.getByRole("heading", { name: `Демо: ${title}` }),
    ).toBeVisible();
    await expect(page.locator(".verdict")).toHaveAttribute(
      "data-assessment",
      level,
    );
    const counts = page.getByLabel("Количество событий по уровню");
    await expect(counts).toContainText(`Явные признаки нарушения: ${strong}`);
    await expect(counts).toContainText(`Требует уточнения: ${review}`);
    expect((await jobFromApi(id)).verdict).toBe(
      level === "clear" ? "no_violation" : "violation",
    );
    await contrast(page);
    await noOverflow(page);
    if (level === "clear")
      await page.screenshot({
        path: path.join(RUN, "assessment-green-desktop.png"),
        fullPage: true,
      });
  });
}

test("mixed assessments preserve row/marker colors, keyboard selection, export and real restart recovery", async ({
  page,
}) => {
  await open(page);
  const id = await start(page, "mixed_assessments");
  const job = await jobFromApi(id);
  const levels = [
    "strong_evidence",
    "needs_review",
    "strong_evidence",
    "needs_review",
  ];
  expect(
    job.violations.map((event: { assessment: string }) => event.assessment),
  ).toEqual(levels);
  const rows = page.getByLabel("Найденные события").getByRole("button");
  const markers = page
    .getByLabel("Отметки событий на шкале")
    .getByRole("button");
  await expect(rows).toHaveCount(4);
  await expect(markers).toHaveCount(4);
  for (let index = 0; index < 4; index++) {
    await expect(rows.nth(index)).toHaveAttribute(
      "data-assessment",
      levels[index],
    );
    await expect(markers.nth(index)).toHaveAttribute(
      "data-assessment",
      levels[index],
    );
    expect(
      await rows
        .nth(index)
        .locator(".assessment-badge")
        .evaluate((node) => getComputedStyle(node).color),
    ).toBe(
      await markers.nth(index).evaluate((node) => getComputedStyle(node).color),
    );
  }
  await expect(page.getByLabel("Количество событий по уровню")).toContainText(
    "Явные признаки нарушения: 2",
  );
  await expect(page.getByLabel("Количество событий по уровню")).toContainText(
    "Требует уточнения: 2",
  );
  await expect(page.locator(".event-detail")).toHaveAttribute(
    "data-assessment",
    "strong_evidence",
  );
  await expect(
    page.getByRole("link", { name: "Открыть источник" }),
  ).toHaveCount(0);
  await contrast(page);
  await noOverflow(page);
  await page.screenshot({
    path: path.join(RUN, "assessment-mixed-desktop.png"),
    fullPage: true,
  });
  await markers.nth(1).focus();
  expect(
    await markers
      .nth(1)
      .evaluate((node) => getComputedStyle(node).outlineColor),
  ).toBe(await markers.nth(1).evaluate((node) => getComputedStyle(node).color));
  await page.keyboard.press("Enter");
  await expect(rows.nth(1)).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".event-detail")).toHaveAttribute(
    "data-assessment",
    "needs_review",
  );
  await expect
    .poll(() =>
      page
        .locator("video")
        .evaluate((video: HTMLVideoElement) => video.currentTime),
    )
    .toBeCloseTo(job.violations[1].timecode_sec, 2);
  await page.setViewportSize({ width: 390, height: 844 });
  await noOverflow(page);
  await contrast(page);
  await page.screenshot({
    path: path.join(RUN, "assessment-mixed-mobile.png"),
    fullPage: true,
  });
  const frame = page.getByRole("button", { name: /^Увеличить кадр 1,/ });
  await frame.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(frame).toBeFocused();
  expect((await exported(page)).violations).toEqual(job.violations);
  await restartBackend();
  await page.reload();
  await expect(page.locator(".verdict")).toHaveAttribute(
    "data-assessment",
    "strong_evidence",
  );
  await expect(page.locator("video")).toBeVisible();
  expect((await exported(page)).violations).toEqual(job.violations);
  expect((await jobFromApi(id)).violations).toEqual(job.violations);
  await expect(
    page.getByLabel("Отметки событий на шкале").getByRole("button"),
  ).toHaveCount(4);
});

test("legacy restored response is yellow, explains missing assessment and exports original fields", async ({
  page,
}) => {
  await open(page);
  const id = await start(page, "strong_evidence");
  const legacy = await jobFromApi(id);
  for (const event of legacy.violations) {
    delete event.assessment;
    delete event.assessment_reason;
  }
  await page.route(`**/api/v1/jobs/${id}`, (route) =>
    route.fulfill({ json: legacy }),
  );
  await page.reload();
  await expect(page.locator(".verdict")).toHaveAttribute(
    "data-assessment",
    "needs_review",
  );
  await expect(page.getByText(/Уровень оценки не передан/)).toBeVisible();
  await expect(page.getByText(/Объяснение уровня не передано/)).toBeVisible();
  const saved = await exported(page);
  expect(saved.violations[0]).not.toHaveProperty("assessment");
  expect(saved.violations[0]).not.toHaveProperty("assessment_reason");
  await page.unrouteAll();
});

test("unknown levels, contradictions and server timeout never acquire a green verdict", async ({
  page,
}) => {
  await open(page);
  const id = await start(page, "strong_evidence");
  const valid = await jobFromApi(id);
  for (const bad of [
    {
      ...valid,
      violations: [{ ...valid.violations[0], assessment: "unknown_level" }],
    },
    { ...valid, verdict: "no_violation" },
    {
      ...valid,
      verdict: "no_violation",
      violations: [],
      error: "Broken result",
    },
    {
      ...valid,
      status: "failed",
      stage: "failed",
      verdict: null,
      violations: [],
      error: "Истекло время проверки.",
      error_code: "TIMEOUT",
    },
  ]) {
    await page.route(`**/api/v1/jobs/${id}`, (route) =>
      route.fulfill({ json: bad }),
    );
    await page.reload();
    await expect(
      page.getByRole("heading", { name: "Проверка не завершена" }),
    ).toBeVisible();
    await expect(page.locator(".completed-result")).toHaveCount(0);
    await expect(page.locator('[data-assessment="clear"]')).toHaveCount(0);
    await expect(page.locator('[data-assessment="incomplete"]')).toBeVisible();
    await page.unrouteAll();
  }
});

test("live evidence renders the rule link and unprefixed assessment label", async ({
  page,
}) => {
  await open(page);
  const id = await start(page, "strong_evidence");
  const fixture = await jobFromApi(id);
  fixture.mode = "live";
  fixture.demo_scenario = null;
  const event = fixture.violations[0];
  event.rule_id = "test-rule";
  event.rule = {
    ...event.rule,
    id: "test-rule",
    is_demo: false,
    title: "Тестовая запись каталога",
    url: "https://example.test/rule",
  };
  await page.route(`**/api/v1/jobs/${id}`, (route) =>
    route.fulfill({ json: fixture }),
  );
  await page.reload();
  await expect(
    page.getByRole("heading", {
      name: "Явные признаки нарушения",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Открыть источник" }),
  ).toHaveAttribute("href", "https://example.test/rule");
  await page.unrouteAll();
});
