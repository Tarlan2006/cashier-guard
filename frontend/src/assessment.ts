import { ApiError, parseJob } from "./api";
import type { Assessment, Job, Violation } from "./api";

export type ResultLevel = Assessment | "clear" | "incomplete";
export type EventAssessment = {
  level: Assessment;
  label: string;
  reason: string;
  legacy: boolean;
};
export type ResultAssessment = {
  level: ResultLevel;
  label: string;
  strongCount: number;
  reviewCount: number;
  totalCount: number;
};
const labels: Record<ResultLevel, string> = {
  strong_evidence: "Явные признаки нарушения",
  needs_review: "Требует уточнения",
  clear: "Нарушений не обнаружено",
  incomplete: "Проверка не завершена",
};

// The UI never estimates confidence. Missing legacy assessments are presented
// for human review without adding invented assessment fields to the source JSON.
export function getEventAssessment(event: Violation): EventAssessment {
  const legacy = event.assessment == null;
  const level = event.assessment ?? "needs_review";
  const reason =
    typeof event.assessment_reason === "string"
      ? event.assessment_reason.trim()
      : undefined;
  if (
    !["strong_evidence", "needs_review"].includes(level) ||
    (event.assessment_reason != null && !reason) ||
    (level === "strong_evidence" && !reason)
  )
    throw new ApiError("protocol", "Некорректный уровень оценки события.");
  const legacyNotice = legacy
    ? "Уровень оценки не передан. Событие требует проверки человеком. "
    : "";
  return {
    level,
    label: labels[level],
    reason: `${legacyNotice}${reason ?? "Объяснение уровня не передано."}`,
    legacy,
  };
}

export function getResultAssessment(job: Job | null): ResultAssessment {
  const incomplete: ResultAssessment = {
    level: "incomplete",
    label: labels.incomplete,
    strongCount: 0,
    reviewCount: 0,
    totalCount: 0,
  };
  if (!job || job.status !== "done") return incomplete;
  try {
    // Callers normally receive an already parsed job, but malformed restored or
    // directly supplied data must never acquire a reassuring green treatment.
    parseJob(job, job.job_id);
    let strongCount = 0;
    let reviewCount = 0;
    for (const event of job.violations) {
      if (getEventAssessment(event).level === "strong_evidence") strongCount++;
      else reviewCount++;
    }
    const level: ResultLevel = strongCount
      ? "strong_evidence"
      : reviewCount
        ? "needs_review"
        : "clear";
    return {
      level,
      label: labels[level],
      strongCount,
      reviewCount,
      totalCount: strongCount + reviewCount,
    };
  } catch {
    return incomplete;
  }
}
