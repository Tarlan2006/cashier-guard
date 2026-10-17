import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import type { Job, Violation } from "./api";
import { getEventAssessment, getResultAssessment } from "./assessment";

const legacy: Violation = {
  type: "Демо-событие",
  timecode_sec: 1.5,
  description: "Сценарий для проверки интерфейса.",
  evidence_frames: [{ timestamp_sec: 1.5, image_base64: "demo-frame" }],
  rule: null,
};
const strong: Violation = {
  ...legacy,
  assessment: "strong_evidence",
  assessment_reason: "Демо: условное убедительное визуальное доказательство.",
};
const review: Violation = {
  ...legacy,
  assessment: "needs_review",
  assessment_reason: "Демо: часть действия скрыта от камеры.",
};
const job = (events: Violation[] = []): Job => ({
  job_id: "assessment-fixture",
  filename: "fixture.mp4",
  status: "done",
  stage: "done",
  mode: "demo",
  duration_sec: 4,
  error: null,
  verdict: events.length ? "violation" : "no_violation",
  violations: events,
});

describe("event assessments", () => {
  it.each([
    [strong, "strong_evidence", "Явные признаки нарушения"],
    [review, "needs_review", "Требует уточнения"],
  ] as const)(
    "displays the transmitted %s assessment",
    (event, level, label) => {
      expect(getEventAssessment(event)).toMatchObject({
        level,
        label,
        reason: event.assessment_reason,
        legacy: false,
      });
    },
  );

  it.each([undefined, null])(
    "presents legacy assessment %s as review with an honest missing-level and missing-reason notice",
    (assessment) => {
      const event = { ...legacy, assessment };
      expect(getEventAssessment(event)).toEqual({
        level: "needs_review",
        label: "Требует уточнения",
        reason:
          "Уровень оценки не передан. Событие требует проверки человеком. Объяснение уровня не передано.",
        legacy: true,
      });
      expect(event.assessment).toBe(assessment);
      expect(event).not.toHaveProperty("assessment_reason");
    },
  );

  it("preserves a supplied reason when the level is missing", () => {
    expect(
      getEventAssessment({ ...legacy, assessment_reason: "Описание из ответа" })
        .reason,
    ).toBe(
      "Уровень оценки не передан. Событие требует проверки человеком. Описание из ответа",
    );
  });

  it("admits a review without explanation but explicitly identifies the omission", () => {
    expect(
      getEventAssessment({ ...legacy, assessment: "needs_review" }),
    ).toMatchObject({
      level: "needs_review",
      reason: "Объяснение уровня не передано.",
      legacy: false,
    });
  });

  it.each([
    { ...legacy, assessment: "unknown" },
    { ...strong, assessment_reason: undefined },
    { ...strong, assessment_reason: null },
    { ...strong, assessment_reason: "  " },
    { ...review, assessment_reason: 90 },
  ])("rejects invalid assessment metadata: %j", (invalid) => {
    expect(() => getEventAssessment(invalid as Violation)).toThrow(ApiError);
  });
});

describe("whole-video assessments", () => {
  it.each([
    [[], "clear", 0, 0],
    [[strong], "strong_evidence", 1, 0],
    [[review], "needs_review", 0, 1],
    [[strong, review, legacy, strong], "strong_evidence", 2, 2],
    [[legacy], "needs_review", 0, 1],
  ] as const)(
    "aggregates supplied levels without inventing confidence: %j",
    (events, level, strongCount, reviewCount) => {
      const eventsCopy = [...events];
      expect(getResultAssessment(job(eventsCopy))).toMatchObject({
        level,
        strongCount,
        reviewCount,
        totalCount: events.length,
      });
      expect(getEventAssessment(review).level).toBe("needs_review");
    },
  );

  it.each([
    null,
    { ...job(), status: "processing", verdict: null },
    { ...job(), status: "failed", verdict: null, error: "Timeout" },
    { ...job(), status: "failed", error: "Timeout" },
    { ...job(), error: "Unexpected error" },
    { ...job(), error_code: "ANALYSIS_TIMEOUT" },
    { ...job(), violations: [review] },
    { ...job(), verdict: "violation" },
    { ...job([review]), violations: [{ ...review, assessment: "unknown" }] },
    { ...job(), violations: undefined },
    { ...job(), duration_sec: Number.NaN },
  ])("keeps incomplete or contradictory data neutral: %j", (invalid) => {
    expect(getResultAssessment(invalid as Job | null)).toEqual({
      level: "incomplete",
      label: "Проверка не завершена",
      strongCount: 0,
      reviewCount: 0,
      totalCount: 0,
    });
  });

  it("keeps JSON exports faithful to new and legacy source fields", () => {
    const result = job([strong, review, legacy]);
    const before = JSON.stringify(result);
    getResultAssessment(result);
    result.violations.forEach(getEventAssessment);
    expect(JSON.stringify(result)).toBe(before);
    const exported: Job = JSON.parse(before);
    expect(exported.violations[0].assessment).toBe("strong_evidence");
    expect(exported.violations[0].assessment_reason).toBe(
      strong.assessment_reason,
    );
    expect(exported.violations[2]).not.toHaveProperty("assessment");
    expect(exported.violations[2]).not.toHaveProperty("assessment_reason");
  });
});
