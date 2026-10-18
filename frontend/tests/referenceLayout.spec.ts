import { saveApiKey } from "./settingsFlow";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { prepareAnalysisFixture } from "./analysisFixture";
import { KEY, RUN, VIDEO, prepareRuntime, stopBackend } from "./runtime";

test.beforeAll(async () => {
  await prepareRuntime();
});
test.afterAll(async () => {
  await stopBackend();
});

async function atDocumentTop(page: Page) {
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement)
      document.activeElement.blur();
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  });
  await expect.poll(() => page.evaluate(() => scrollY)).toBe(0);
  expect((await page.locator(".topbar").boundingBox())?.y).toBe(0);
}

async function noOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBe(true);
}

async function capture(page: Page, name: string) {
  await atDocumentTop(page);
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }),
  );
  await mkdir(RUN, { recursive: true });
  await page.screenshot({
    path: path.join(RUN, `reference-${name}.png`),
    fullPage: true,
    animations: "disabled",
  });
}

for (const width of [1440, 390, 320]) {
  test(`reference navigation preserves real upload and truthful empty states at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: width > 760 ? 1000 : 844 });
    await page.goto("/");
    await expect(
      page.getByText("Анализ видео пока недоступен", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("navigation", { name: "Разделы" }).getByRole("button"),
    ).toHaveCount(8);
    await expect(
      page.locator(".sidebar, .connection, .scenario-select"),
    ).toHaveCount(0);
    for (const item of await page
      .getByRole("navigation", { name: "Разделы" })
      .getByRole("button")
      .all()) {
      const bounds = await item.boundingBox();
      expect(bounds).not.toBeNull();
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    }
    await noOverflow(page);
    if (width !== 320)
      await capture(page, width === 1440 ? "desktop" : "mobile");
    await page.getByLabel("Видео для проверки").setInputFiles(VIDEO);
    await expect
      .poll(() =>
        page
          .locator("video")
          .evaluate((video: HTMLVideoElement) => video.readyState),
      )
      .toBeGreaterThan(0);
    await expect(
      page.getByRole("button", { name: "Проверить видео", exact: true }),
    ).toBeDisabled();
    await noOverflow(page);
    if (width !== 320)
      await capture(
        page,
        width === 1440 ? "selected-desktop" : "selected-mobile",
      );
    for (const [label, heading] of [
      ["Нормативы РК", "Нормативы РК"],
      ["API", "API сервиса"],
      ["Архитектура", "Архитектура обработки"],
    ]) {
      await page
        .getByRole("navigation", { name: "Разделы" })
        .getByRole("button", { name: label, exact: true })
        .click();
      await expect(
        page.getByRole("heading", { name: heading, exact: true }),
      ).toBeVisible();
      const selected = page
        .getByRole("navigation", { name: "Разделы" })
        .getByRole("button", { name: label, exact: true });
      await expect(selected).toHaveAttribute("aria-current", "page");
      await expect(selected).toHaveCSS("color", "rgb(190, 24, 93)");
      await expect(selected).toHaveCSS(
        "background-color",
        "rgb(255, 255, 255)",
      );
      await expect(
        page.locator('.top-navigation button[aria-current="page"]'),
      ).toHaveCount(1);
      if (label === "Архитектура") {
        const panel = page.locator(".architecture-panel");
        await expect(panel).toHaveCSS("background-color", "rgb(255, 255, 255)");
        await expect(panel).toHaveCSS("border-radius", "16px");
        await expect(panel).toHaveCSS("border-top-width", "1px");
        await expect(panel).toHaveCSS(
          "padding-top",
          width > 760 ? "22px" : "18px",
        );
      }
      await noOverflow(page);
      if (width === 1440 || width === 390)
        await capture(
          page,
          (label === "API"
            ? "api"
            : label === "Архитектура"
              ? "architecture"
              : "sources") + (width === 390 ? "-mobile" : ""),
        );
    }
    await page
      .getByRole("button", { name: "Проверка видео", exact: true })
      .click();
    await expect(page.locator("video")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Проверить видео", exact: true }),
    ).toBeDisabled();
  });
}

test("reference result and API use the current labelled fixture without synthetic legal claims", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await prepareAnalysisFixture(page);
  await page.goto("/");
  await saveApiKey(page, KEY);
  await page.getByLabel("Видео для проверки").setInputFiles(VIDEO);
  await page
    .getByRole("button", { name: "Проверить видео", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: /^Демо:/ })).toBeVisible();
  await capture(page, "fixture-result-desktop");
  await page.setViewportSize({ width: 390, height: 844 });
  await noOverflow(page);
  await capture(page, "fixture-result-mobile");
  await page.getByRole("button", { name: "JSON API", exact: true }).click();
  await expect(page.getByLabel("JSON ответа сервиса")).toContainText(
    '"mode": "demo"',
  );
  await noOverflow(page);
  await page.getByRole("button", { name: "Нормативы РК", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Источников пока нет", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Открыть источник", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Проверка видео", exact: true })
    .click();
  await expect(page.locator("video")).toBeVisible();
  await expect(page.getByRole("heading", { name: /^Демо:/ })).toBeVisible();
});
