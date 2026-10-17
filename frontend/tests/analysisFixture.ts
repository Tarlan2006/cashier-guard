import { readFile } from "node:fs/promises";
import path from "node:path";
import type { Page } from "@playwright/test";

const scenarios = new WeakMap<Page, { scenario: string; file: string }>();

// Isolated E2E fixture: expose live availability to exercise the upload UI,
// while the test backend keeps all generated results explicitly labelled demo.
// No fixture controls or availability overrides ship in the application.
export async function prepareAnalysisFixture(page: Page) {
  await page.route(/\/api\/v1\/(health|ready)$/, async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, mode: "live" } });
  });
  await page.route("**/api/v1/analyze", async (route) => {
    const fixture = scenarios.get(page);
    if (!fixture || fixture.scenario === "violation") return route.continue();
    const request = route.request();
    const response = await page.request.post(request.url(), {
      headers: { "X-API-Key": request.headers()["x-api-key"] ?? "" },
      multipart: {
        file: {
          name: path.basename(fixture.file),
          mimeType: "video/quicktime",
          buffer: await readFile(fixture.file),
        },
        demo_scenario: fixture.scenario,
      },
    });
    await route.fulfill({ response });
  });
}

export function selectAnalysisFixture(page: Page, scenario: string, file: string) {
  scenarios.set(page, { scenario, file });
}
