import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";
import type { Job, Violation } from "../api";
import { ResultPanel } from "./ResultPanel";
import { VideoReview } from "./VideoReview";

const yellow: Violation = {
  type: "Неоднозначное демособытие",
  timecode_sec: 2.5,
  description: "Вымышленный пример для проверки интерфейса.",
  evidence_frames: [{ timestamp_sec: 2.5, image_base64: "ZmFrZQ==" }],
  rule: null,
  assessment: "needs_review",
  assessment_reason: "В демосценарии часть действия закрыта от камеры.",
};
const red: Violation = {
  ...yellow,
  type: "Демонстрация явных признаков",
  timecode_sec: 5,
  assessment: "strong_evidence",
  assessment_reason: "В демосценарии действие видно на нескольких кадрах.",
};
const base: Job = {
  job_id: "assessment-ui",
  status: "done",
  stage: "done",
  mode: "demo",
  filename: "synthetic.mov",
  duration_sec: 12,
  verdict: "violation",
  violations: [yellow],
  error: null,
};
const actions = {
  onSelect: vi.fn(),
  onSeek: vi.fn(),
  canPlay: true,
  onFrame: vi.fn(),
  onResume: vi.fn(),
  canResume: true,
  onReset: vi.fn(),
  hasKey: true,
};
function panel(job: Job, overrides = {}) {
  return (
    <ResultPanel
      {...actions}
      job={job}
      phase="done"
      issue={null}
      activeEvent={0}
      {...overrides}
    />
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal(
    "URL",
    Object.assign(URL, {
      createObjectURL: vi.fn(() => "blob:test"),
      revokeObjectURL: vi.fn(),
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("assessment result presentation", () => {
  it.each([
    [[], "no_violation", "clear", "Нарушений не обнаружено", 0, 0],
    [[red], "violation", "strong_evidence", "Явные признаки нарушения", 1, 0],
    [[yellow], "violation", "needs_review", "Требует уточнения", 0, 1],
    [
      [yellow, red, yellow, red],
      "violation",
      "strong_evidence",
      "Явные признаки нарушения",
      2,
      2,
    ],
  ] as const)(
    "shows %s with a labelled overall level and accurate counts",
    (events, verdict, level, label, strong, review) => {
      const { container } = render(
        panel({ ...base, verdict, violations: [...events] }),
      );
      expect(
        screen.getByRole("heading", { name: `Демо: ${label}` }),
      ).toBeTruthy();
      expect(
        container.querySelector(".verdict")?.getAttribute("data-assessment"),
      ).toBe(level);
      const counts = within(
        screen.getByLabelText("Количество событий по уровню"),
      );
      expect(
        counts.getByText(`Явные признаки нарушения:`, { exact: false })
          .textContent,
      ).toContain(String(strong));
      expect(
        counts.getByText(`Требует уточнения:`, { exact: false }).textContent,
      ).toContain(String(review));
      expect(container.querySelector(".verdict svg")).toBeTruthy();
      if (strong)
        expect(screen.getByText(/Решение принимает человек/)).toBeTruthy();
    },
  );

  it("keeps yellow and red event rows, selected evidence and timeline markers consistent", () => {
    const job = { ...base, violations: [yellow, red] };
    const view = render(panel(job));
    const rows = within(
      screen.getByLabelText("Найденные события"),
    ).getAllByRole("button");
    expect(rows.map((row) => row.dataset.assessment)).toEqual([
      "needs_review",
      "strong_evidence",
    ]);
    expect(view.container.querySelector("article")?.dataset.assessment).toBe(
      "needs_review",
    );
    fireEvent.click(rows[1]);
    expect(actions.onSelect).toHaveBeenCalledWith(1);
    view.rerender(panel(job, { activeEvent: 1 }));
    expect(view.container.querySelector("article")?.dataset.assessment).toBe(
      "strong_evidence",
    );
    expect(screen.getByText(red.assessment_reason!)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^Увеличить кадр 1/ }));
    expect(actions.onFrame).toHaveBeenCalledWith(red.evidence_frames[0]);

    render(
      <VideoReview
        file={new File(["fixture"], "video.mov")}
        events={job.violations}
        activeEvent={1}
        normalizedDuration={12}
        sourceTimeOffset={0}
        onSelect={actions.onSelect}
        onRemove={vi.fn()}
        onPreviewAvailabilityChange={vi.fn()}
        disabled={false}
      />,
    );
    const video = screen.getByLabelText("Предпросмотр загруженного видео");
    Object.defineProperty(video, "duration", { value: 12 });
    fireEvent.loadedMetadata(video);
    const markers = within(
      screen.getByLabelText("Отметки событий на шкале"),
    ).getAllByRole("button");
    expect(markers.map((marker) => marker.dataset.assessment)).toEqual([
      "needs_review",
      "strong_evidence",
    ]);
    expect(markers[0].getAttribute("aria-label")).toContain(
      "Требует уточнения",
    );
    expect(markers[1].getAttribute("aria-label")).toContain(
      "Явные признаки нарушения",
    );
    expect(markers[1].getAttribute("aria-pressed")).toBe("true");
  });

  it("labels legacy absence honestly without fabricating an assessment", () => {
    const {
      assessment: _level,
      assessment_reason: _reason,
      ...legacy
    } = yellow;
    render(panel({ ...base, violations: [legacy] }));
    expect(
      screen.getByRole("heading", { name: "Демо: Требует уточнения" }),
    ).toBeTruthy();
    expect(screen.getByText(/Уровень оценки не передан/)).toBeTruthy();
    expect(screen.getByText(/Объяснение уровня не передано/)).toBeTruthy();
    expect(legacy).not.toHaveProperty("assessment");
  });

  it.each([
    { ...base, verdict: "no_violation", violations: [yellow] },
    { ...base, violations: [{ ...yellow, assessment: "unknown" }] },
    { ...base, violations: [{ ...red, assessment_reason: null }] },
  ])("shows neutral state for a corrupt result", (job) => {
    const { container } = render(panel(job as Job));
    expect(
      screen.getByRole("heading", { name: "Проверка не завершена" }),
    ).toBeTruthy();
    expect(container.querySelector(".verdict")).toBeNull();
    expect(container.querySelector(".completed-result")).toBeNull();
  });

  it.each(["processing", "failed", "interrupted"])(
    "does not display stale green while %s",
    (phase) => {
      const { container } = render(
        panel(
          { ...base, verdict: "no_violation", violations: [] },
          {
            phase,
            issue:
              phase === "processing"
                ? null
                : new ApiError("timeout", "Время ожидания истекло."),
          },
        ),
      );
      expect(
        screen.getByText("Проверка не завершена", { exact: true }),
      ).toBeTruthy();
      expect(container.querySelector(".completed-result")).toBeNull();
      expect(container.querySelector('[data-assessment="clear"]')).toBeNull();
    },
  );
});
