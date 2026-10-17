import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import App from "./App";
import { request } from "./api";
import { API_KEY_STORAGE } from "./hooks/useReview";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  request: vi.fn(),
}));
vi.mock("./hooks/useServiceStatus", () => ({
  useServiceStatus: () => ({
    checked: true,
    health: { mode: "live", max_upload_mb: 100 },
    readiness: { mode: "live", ready: true, checks: {} },
    refresh: vi.fn(),
  }),
}));
const requestMock = vi.mocked(request);
const video = () =>
  new File(["video-fixture"], "fixture.mov", { type: "video/quicktime" });

beforeEach(() => {
  sessionStorage.clear();
  requestMock.mockReset();
  vi.stubGlobal(
    "URL",
    Object.assign(URL, {
      createObjectURL: vi.fn(() => "blob:settings-test-video"),
      revokeObjectURL: vi.fn(),
    }),
  );
});
afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.unstubAllGlobals();
});

it("saves only submitted key changes, preserves video across sections and authorizes analysis", async () => {
  const user = userEvent.setup();
  render(<App />);
  expect(
    screen.queryByLabelText("Ключ доступа к API", { exact: true }),
  ).toBeNull();
  fireEvent.change(screen.getByLabelText("Видео для проверки"), {
    target: { files: [video()] },
  });
  expect(
    screen.getByText("Настройте подключение для проверки видео"),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Проверить видео",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  await user.click(screen.getByRole("link", { name: "Открыть настройки" }));
  const field = screen.getByLabelText("Ключ доступа к API", {
    exact: true,
  }) as HTMLInputElement;
  expect(field.type).toBe("password");
  await user.type(field, "  saved-settings-key  ");
  expect(sessionStorage.getItem(API_KEY_STORAGE)).toBeNull();
  await user.click(screen.getByRole("button", { name: "Показать ключ" }));
  expect(field.type).toBe("text");
  await user.click(screen.getByRole("button", { name: "Скрыть ключ" }));
  expect(field.type).toBe("password");
  await user.click(screen.getByRole("button", { name: "Сохранить" }));
  await waitFor(() =>
    expect(sessionStorage.getItem(API_KEY_STORAGE)).toBe("saved-settings-key"),
  );
  expect(screen.getByRole("status").textContent).toBe("Ключ сохранён");
  await user.clear(field);
  await user.type(field, "unsaved-draft");
  for (const name of ["Нормативы РК", "API", "Архитектура", "Настройки"]) {
    await user.click(screen.getByRole("button", { name }));
  }
  expect(
    (screen.getByLabelText("Ключ доступа к API", {}) as HTMLInputElement).value,
  ).toBe("saved-settings-key");
  await user.click(screen.getByRole("button", { name: "Проверка видео" }));
  expect(
    screen.queryByLabelText("Ключ доступа к API", { exact: true }),
  ).toBeNull();
  expect(
    screen.queryByText("Настройте подключение для проверки видео"),
  ).toBeNull();
  expect(screen.getByText("fixture.mov", { exact: true })).toBeTruthy();
  requestMock
    .mockResolvedValueOnce({ job_id: "settings-job" })
    .mockResolvedValueOnce({
      job_id: "settings-job",
      mode: "live",
      status: "done",
      stage: "done",
      filename: "fixture.mov",
      duration_sec: 12,
      verdict: "no_violation",
      violations: [],
      error: null,
    });
  await user.click(screen.getByRole("button", { name: "Проверить видео" }));
  await waitFor(() =>
    expect(requestMock).toHaveBeenCalledWith(
      "/analyze",
      "saved-settings-key",
      expect.objectContaining({ method: "POST", body: expect.any(FormData) }),
    ),
  );
  await waitFor(() =>
    expect(requestMock).toHaveBeenCalledWith(
      "/jobs/settings-job",
      "saved-settings-key",
      expect.any(Object),
    ),
  );
});

it("deletes the stored key, keeps the selected file and requires setup after remount", async () => {
  sessionStorage.setItem(API_KEY_STORAGE, "existing-settings-key");
  const user = userEvent.setup();
  const first = render(<App />);
  fireEvent.change(screen.getByLabelText("Видео для проверки"), {
    target: { files: [video()] },
  });
  await user.click(screen.getByRole("button", { name: "Настройки" }));
  expect(
    (screen.getByLabelText("Ключ доступа к API", {}) as HTMLInputElement).value,
  ).toBe("existing-settings-key");
  await user.click(screen.getByRole("button", { name: "Удалить ключ" }));
  await waitFor(() =>
    expect(sessionStorage.getItem(API_KEY_STORAGE)).toBeNull(),
  );
  expect(screen.getByRole("status").textContent).toBe("Ключ удалён");
  await user.click(screen.getByRole("button", { name: "Проверка видео" }));
  expect(screen.getByText("fixture.mov", { exact: true })).toBeTruthy();
  expect(
    screen.getByText("Настройте подключение для проверки видео"),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Проверить видео",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(requestMock).not.toHaveBeenCalled();
  first.unmount();
  render(<App />);
  await user.click(screen.getByRole("button", { name: "Настройки" }));
  expect(
    (screen.getByLabelText("Ключ доступа к API", {}) as HTMLInputElement).value,
  ).toBe("");
  expect(
    (
      screen.getByRole("button", {
        name: "Сохранить",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});
