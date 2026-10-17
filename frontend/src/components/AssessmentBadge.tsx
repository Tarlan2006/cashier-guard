import {
  CircleDashed,
  CircleHelp,
  CheckCircle2,
  TriangleAlert,
} from "lucide-react";
import type { ResultLevel } from "../assessment";

export function AssessmentIcon({
  level,
  size = 18,
}: {
  level: ResultLevel;
  size?: number;
}) {
  const Icon = {
    strong_evidence: TriangleAlert,
    needs_review: CircleHelp,
    clear: CheckCircle2,
    incomplete: CircleDashed,
  }[level];
  return <Icon size={size} aria-hidden="true" />;
}

export function AssessmentBadge({
  level,
  label,
}: {
  level: ResultLevel;
  label: string;
}) {
  return (
    <span className={`assessment-badge assessment-${level}`}>
      <AssessmentIcon level={level} />
      <span>{label}</span>
    </span>
  );
}
