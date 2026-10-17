import { expect, type Page } from "@playwright/test";

export async function openSettings(page: Page) {
  await page
    .getByRole("navigation", { name: "Разделы" })
    .getByRole("button", { name: "Настройки", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Подключение API", exact: true }),
  ).toBeVisible();
}

export async function saveApiKey(page: Page, key: string) {
  await openSettings(page);
  await page.getByLabel("Ключ доступа к API", { exact: true }).fill(key);
  const save = page.getByRole("button", { name: "Сохранить", exact: true });
  if (await save.isEnabled()) {
    await save.click();
    await expect(page.getByRole("status")).toHaveText("Ключ сохранён");
  }
  await page
    .getByRole("navigation", { name: "Разделы" })
    .getByRole("button", { name: "Проверка видео", exact: true })
    .click();
}
