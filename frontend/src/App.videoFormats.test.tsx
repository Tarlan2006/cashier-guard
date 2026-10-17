import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { Job } from "./api";
import { useReview } from "./hooks/useReview";
import { useServiceStatus } from "./hooks/useServiceStatus";

vi.mock("./hooks/useReview", () => ({
  readKey: () => "isolated-test-key",
  useReview: vi.fn(),
}));
vi.mock("./hooks/useServiceStatus", () => ({ useServiceStatus: vi.fn() }));

const reviewMock = vi.mocked(useReview);
const serviceMock = vi.mocked(useServiceStatus);
const formats = [
  ["MOV", "video/quicktime"],
  ["mp4", "video/mp4"],
  ["avi", "video/x-msvideo"],
  ["mkv", "application/octet-stream"],
  ["webm", ""],
] as const;

const processing: Job = {
  job_id: "test-job",
  status: "processing",
  stage: "preparing",
  mode: "live",
  filename: "synthetic.mkv",
  duration_sec: 12,
  verdict: null,
  violations: [],
  error: null,
  deadline_at: new Date(Date.now() + 290_000).toISOString(),
};

beforeEach(() => {
  vi.stubGlobal(
    "URL",
    Object.assign(URL, {
      createObjectURL: vi.fn(() => "blob:isolated-test-video"),
      revokeObjectURL: vi.fn(),
    }),
  );
  reviewMock.mockReturnValue({
    job: null,
    phase: "idle",
    issue: null,
    busy: false,
    restoredId: undefined,
    submit: vi.fn().mockResolvedValue(undefined),
    reset: vi.fn(),
    resume: vi.fn(),
    canResume: false,
  });
  serviceMock.mockReturnValue({
    health: { status: "ok", mode: "live", max_upload_mb: 100 },
    readiness: { ready: true, mode: "live", checks: {} },
    checked: true,
    refresh: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("video formats in the upload form", () => {
  it.each(formats)(
    "accepts .%s through the file picker",
    async (extension, type) => {
      const user = userEvent.setup();
      render(<App />);
      const file = new File(["synthetic bytes"], `synthetic.${extension}`, {
        type,
      });
      await user.upload(screen.getByLabelText("Видео для проверки"), file);
      expect(screen.getByText(file.name)).toBeTruthy();
      const submit = screen.getByRole("button", { name: "Проверить видео" });
      expect((submit as HTMLButtonElement).disabled).toBe(false);
      await user.click(submit);
      expect(reviewMock.mock.results[0].value.submit).toHaveBeenCalledWith(
        file,
      );
    },
  );

  it.each(formats)("accepts .%s through drag and drop", (extension, type) => {
    render(<App />);
    const file = new File(["synthetic bytes"], `synthetic.${extension}`, {
      type,
    });
    fireEvent.drop(
      screen.getByRole("button", { name: /Перетащите видео сюда/ }),
      {
        dataTransfer: { files: [file] },
      },
    );
    expect(screen.getByText(file.name)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Проверить видео" }));
    expect(reviewMock.mock.results[0].value.submit).toHaveBeenCalledWith(file);
  });

  it("lists all five extensions and MIME choices in the picker", () => {
    render(<App />);
    const accept = (
      screen.getByLabelText("Видео для проверки") as HTMLInputElement
    ).accept;
    for (const extension of ["mov", "mp4", "avi", "mkv", "webm"]) {
      expect(accept.split(",")).toContain(`.${extension}`);
    }
    for (const mime of [
      "video/quicktime",
      "video/mp4",
      "video/x-msvideo",
      "video/x-matroska",
      "video/webm",
    ]) {
      expect(accept.split(",")).toContain(mime);
    }
    expect(
      screen.getByText(/MOV, MP4, AVI, MKV и WEBM · до 100 МБ/),
    ).toBeTruthy();
  });

  it.each(["picker", "drop"])(
    "rejects an unsupported extension through %s",
    (method) => {
      render(<App />);
      const file = new File(["unsupported"], "synthetic.flv", {
        type: "video/mp4",
      });
      if (method === "picker") {
        fireEvent.change(screen.getByLabelText("Видео для проверки"), {
          target: { files: [file] },
        });
      } else {
        fireEvent.drop(
          screen.getByRole("button", { name: /Перетащите видео сюда/ }),
          {
            dataTransfer: { files: [file] },
          },
        );
      }
      expect(screen.getByRole("alert").textContent).toContain(
        "MOV, MP4, AVI, MKV и WEBM",
      );
      expect(
        screen.queryByRole("button", { name: "Проверить видео" }),
      ).toBeNull();
      expect(reviewMock.mock.results[0].value.submit).not.toHaveBeenCalled();
    },
  );

  it.each(["empty", "oversize"])("preserves the %s file limit", (reason) => {
    render(<App />);
    const file = new File(
      reason === "empty" ? [] : ["video"],
      "synthetic.webm",
    );
    if (reason === "oversize")
      Object.defineProperty(file, "size", { value: 101 * 1024 * 1024 });
    fireEvent.change(screen.getByLabelText("Видео для проверки"), {
      target: { files: [file] },
    });
    expect(screen.getByRole("alert").textContent).toContain(
      reason === "empty" ? "Файл пуст" : "100 МБ",
    );
    expect(
      screen.queryByRole("button", { name: "Проверить видео" }),
    ).toBeNull();
  });

  it("still submits an accepted file when browser preview fails", () => {
    render(<App />);
    const file = new File(["synthetic bytes"], "synthetic.avi", {
      type: "video/x-msvideo",
    });
    fireEvent.change(screen.getByLabelText("Видео для проверки"), {
      target: { files: [file] },
    });
    fireEvent.error(screen.getByLabelText("Предпросмотр загруженного видео"));
    expect(screen.getByText(/Файл можно отправить на анализ/)).toBeTruthy();
    expect(screen.queryByLabelText("Позиция в видео")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    const submit = screen.getByRole("button", { name: "Проверить видео" });
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(submit);
    expect(reviewMock.mock.results[0].value.submit).toHaveBeenCalledWith(file);
  });

  it("disables event seek after preview failure while retaining evidence access", () => {
    const done: Job = {
      ...processing,
      status: "done",
      stage: "done",
      verdict: "violation",
      violations: [
        {
          type: "Тестовое событие",
          timecode_sec: 2,
          description: "Только тест интерфейса",
          evidence_frames: [{ timestamp_sec: 2, image_base64: "dGVzdA==" }],
          rule: null,
        },
      ],
    };
    reviewMock.mockReturnValue({
      ...reviewMock("isolated-test-key"),
      job: done,
      phase: "done",
    });
    render(<App />);
    const file = new File(["synthetic bytes"], "synthetic.mkv");
    fireEvent.change(screen.getByLabelText("Видео для проверки"), {
      target: { files: [file] },
    });
    const video = screen.getByLabelText("Предпросмотр загруженного видео");
    Object.defineProperty(video, "duration", { value: 12 });
    fireEvent.loadedMetadata(video);
    const seekButtons = screen.getAllByRole("button", {
      name: "00:02.000",
    }) as HTMLButtonElement[];
    expect(seekButtons.every((button) => !button.disabled)).toBe(true);
    fireEvent.error(video);
    expect(seekButtons.every((button) => button.disabled)).toBe(true);
    expect(
      (
        screen.getByRole("button", {
          name: /Увеличить кадр 1/,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
    expect(screen.queryByLabelText("Позиция в видео")).toBeNull();
  });

  it("shows conversion as part of the existing preparation stage", () => {
    reviewMock.mockReturnValue({
      ...reviewMock("isolated-test-key"),
      job: processing,
      phase: "processing",
      busy: true,
    });
    render(<App />);
    expect(screen.getByText("Подготовка и преобразование")).toBeTruthy();
    expect(
      screen.getByText("Проверяем файл и преобразуем видео в MP4 для анализа."),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Подготавливаем видео…" }),
    ).toBeNull();
    expect(
      screen.getByText(/включая загрузку, очередь и преобразование/),
    ).toBeTruthy();
  });
});

describe("live-only video analysis", () => {
  const video = () =>
    new File(["synthetic bytes"], "selected.mp4", { type: "video/mp4" });
  function select(file = video()) {
    fireEvent.change(screen.getByLabelText("Видео для проверки"), {
      target: { files: [file] },
    });
    return file;
  }

  it("starts with file selection and removes the analysis action when the file is removed", () => {
    render(<App />);
    expect(
      screen.getByRole("button", { name: /Перетащите видео сюда/ }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Проверить видео" }),
    ).toBeNull();
    expect(screen.queryByLabelText("Тестовый сценарий")).toBeNull();
    expect(screen.queryByText("Запустить демопроверку")).toBeNull();
    expect(document.querySelector(".form-actions")).toBeNull();
    select();
    expect(
      (
        screen.getByRole("button", {
          name: "Проверить видео",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
    fireEvent.click(
      screen.getByRole("button", { name: "Убрать локальное видео" }),
    );
    expect(
      screen.queryByRole("button", { name: "Проверить видео" }),
    ).toBeNull();
    expect(document.querySelector(".form-actions")).toBeNull();
  });

  it.each([
    ["demo", "demo", true],
    ["demo", "live", true],
    ["live", "demo", true],
    ["live", "live", false],
  ] as const)(
    "blocks analysis with health=%s readiness=%s ready=%s",
    (healthMode, readinessMode, ready) => {
      serviceMock.mockReturnValue({
        health: { status: "ok", mode: healthMode, max_upload_mb: 100 },
        readiness: { ready, mode: readinessMode, checks: {} },
        checked: true,
        refresh: vi.fn(),
      });
      render(<App />);
      expect(screen.getByText("Анализ видео пока недоступен")).toBeTruthy();
      select();
      const submit = screen.getByRole("button", { name: "Проверить видео" });
      expect((submit as HTMLButtonElement).disabled).toBe(true);
      fireEvent.click(submit);
      expect(reviewMock.mock.results[0].value.submit).not.toHaveBeenCalled();
      expect(screen.queryByLabelText("Тестовый сценарий")).toBeNull();
      expect(screen.queryByText("Запустить демопроверку")).toBeNull();
    },
  );

  it.each([false, true])(
    "keeps uploads blocked when service checks are pending or failed (checked=%s)",
    (checked) => {
      serviceMock.mockReturnValue({
        health: null,
        readiness: null,
        checked,
        refresh: vi.fn(),
      });
      render(<App />);
      select();
      const submit = screen.getByRole("button", { name: "Проверить видео" });
      expect((submit as HTMLButtonElement).disabled).toBe(true);
      fireEvent.click(submit);
      expect(reviewMock.mock.results[0].value.submit).not.toHaveBeenCalled();
      if (checked) expect(screen.getByText("Сервер недоступен")).toBeTruthy();
    },
  );

  it("keeps a restored demo result explicitly fictional", () => {
    reviewMock.mockReturnValue({
      ...reviewMock("isolated-test-key"),
      job: {
        ...processing,
        mode: "demo",
        status: "done",
        stage: "done",
        verdict: "no_violation",
      },
      phase: "done",
    });
    render(<App />);
    expect(screen.getByRole("heading", { name: /^Демо:/ })).toBeTruthy();
    expect(
      screen.getByText(/ML не анализировал содержимое видео/),
    ).toBeTruthy();
    expect(
      screen.queryByRole("heading", {
        name: "Нарушений не обнаружено",
      }),
    ).toBeNull();
  });
});

describe("reference layout navigation", () => {
  it("opens factual sections without replacing the selected video or inventing an API response", () => {
    render(<App />);
    const file = new File(["local fixture"], "navigation.mp4", {
      type: "video/mp4",
    });
    fireEvent.change(screen.getByLabelText("Видео для проверки"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "API" }));
    expect(screen.getByRole("heading", { name: "API сервиса" })).toBeTruthy();
    expect(screen.queryByLabelText("JSON ответа сервиса")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Нормативы РК" }));
    expect(
      screen.getByRole("heading", { name: "Источников пока нет" }),
    ).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Открыть источник" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Архитектура" }));
    expect(
      screen.getByRole("heading", { name: "Архитектура обработки" }),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Проверка видео" }));
    expect(screen.getByText(file.name)).toBeTruthy();
    expect(
      (
        screen.getByRole("button", {
          name: "Проверить видео",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
    expect(reviewMock.mock.results[0].value.submit).not.toHaveBeenCalled();
  });
});
