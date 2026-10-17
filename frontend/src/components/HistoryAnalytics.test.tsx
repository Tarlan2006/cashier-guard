import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { request } from "../api";
import {
  AnalyticsPanel,
  HistoryPanel,
  emptyFilters,
  periodDates,
} from "./HistoryAnalytics";
vi.mock("../api", async (original) => ({
  ...(await original<typeof import("../api")>()),
  request: vi.fn(),
}));
const fetchMock = vi.mocked(request);
afterEach(() => {
  cleanup();
  fetchMock.mockReset();
});
it("keeps a missing API connection private and routes to settings without a request", async () => {
  const settings = vi.fn();
  render(
    <HistoryPanel
      apiKey=""
      filters={emptyFilters}
      onFilters={vi.fn()}
      onOpen={vi.fn()}
      onDeleted={vi.fn()}
      onSettings={settings}
      canOpen
    />,
  );
  expect(fetchMock).not.toHaveBeenCalled();
  await userEvent.click(
    screen.getByRole("link", { name: "Открыть настройки" }),
  );
  expect(settings).toHaveBeenCalledOnce();
});
it("shows an error instead of inventing counts for malformed analytics and supports retry", async () => {
  fetchMock
    .mockResolvedValueOnce({ successful_videos: 99 })
    .mockResolvedValueOnce({
      successful_videos: 0,
      videos_with_events: 0,
      detected_events: 0,
      confirmed_events: 0,
      rejected_events: 0,
      unreviewed_events: 0,
      top_types: [],
      date_basis: "created_at",
    });
  render(
    <AnalyticsPanel apiKey="fixture" onSettings={vi.fn()} onDrill={vi.fn()} />,
  );
  await screen.findByRole("alert");
  expect(screen.queryByText("99")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Повторить" }));
  await screen.findByText("За выбранный период событий нет.");
  expect(fetchMock).toHaveBeenCalledTimes(2);
});
it("drills the exact category into history with the same dates and live completed filters", async () => {
  fetchMock.mockResolvedValue({
    successful_videos: 4,
    videos_with_events: 2,
    detected_events: 5,
    confirmed_events: 1,
    rejected_events: 1,
    unreviewed_events: 3,
    top_types: [
      {
        category_id: "exact-category",
        type: "Exact category fixture",
        detected: 5,
        confirmed: 1,
      },
    ],
    date_basis: "created_at",
  });
  const drill = vi.fn();
  render(
    <AnalyticsPanel apiKey="fixture" onSettings={vi.fn()} onDrill={drill} />,
  );
  await screen.findByRole("button", { name: /Exact category fixture/ });
  await userEvent.click(
    screen.getByRole("button", { name: /Exact category fixture/ }),
  );
  expect(drill).toHaveBeenCalledWith(
    expect.objectContaining({
      status: "done",
      mode: "live",
      category_id: "exact-category",
      categoryLabel: "Exact category fixture",
      period: "custom",
    }),
  );
  await waitFor(() =>
    expect(fetchMock.mock.calls[0][0]).toMatch(/^\/analytics\?/),
  );
});
it("converts inclusive local calendar dates into an exclusive end boundary", () => {
  const result = periodDates("custom", "2026-10-01", "2026-10-17");
  expect(new Date(result.query.date_from!).getDate()).toBe(1);
  expect(new Date(result.query.date_to!).getDate()).toBe(18);
  expect(() => periodDates("custom", "2026-10-18", "2026-10-17")).toThrow();
});
