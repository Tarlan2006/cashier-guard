import { Terminal } from "lucide-react";
import type { Job } from "../api";
import { getResultAssessment } from "../assessment";
import { AssessmentIcon } from "./AssessmentBadge";

export function ReviewSummary({
  job,
  onShowApi,
}: {
  job: Job;
  onShowApi?: () => void;
}) {
  const result = getResultAssessment(job);
  if (result.level === "incomplete") return null;
  return (
    <div
      className={`verdict assessment-${result.level}`}
      data-assessment={result.level}
    >
      <div className="verdict-symbol">
        <AssessmentIcon level={result.level} size={23} />
      </div>
      <div className="verdict-copy">
        <h3>{job.mode === "demo" ? `Демо: ${result.label}` : result.label}</h3>
        <p>
          {job.mode === "demo"
            ? "События и уровни заданы тестовым сценарием. ML не анализировал содержимое видео."
            : "Проверьте доказательства и примите решение самостоятельно."}
        </p>
        {result.level === "strong_evidence" && (
          <p>
            Это признаки нарушения, а не окончательное заключение. Решение
            принимает человек.
          </p>
        )}
      </div>
      {onShowApi && (
        <div className="summary-actions">
          <span className="event-total">
            Событий: <strong>{result.totalCount}</strong>
          </span>
          <button className="button dark" onClick={onShowApi}>
            <Terminal size={15} />
            JSON API
          </button>
        </div>
      )}
    </div>
  );
}
