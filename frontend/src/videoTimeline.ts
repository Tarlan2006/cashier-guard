type VideoTimeline = { duration: number; offset: number; aligned: boolean };

// Browser media timelines differ for nonzero container timestamps. Compare the
// browser duration with both supported timelines, allowing a final-frame rounding
// difference. Never guess a mapping when neither timeline matches.
export function resolveVideoTimeline(
  browserDuration: number,
  normalizedDuration?: number | null,
  sourceOffset?: number | null,
): VideoTimeline {
  if (!Number.isFinite(browserDuration) || browserDuration <= 0)
    return { duration: 0, offset: 0, aligned: false };
  if (normalizedDuration == null || sourceOffset == null)
    return { duration: browserDuration, offset: 0, aligned: true };
  if (
    !Number.isFinite(normalizedDuration) ||
    normalizedDuration <= 0 ||
    !Number.isFinite(sourceOffset)
  )
    return { duration: browserDuration, offset: 0, aligned: false };
  if (sourceOffset === 0)
    return { duration: normalizedDuration, offset: 0, aligned: true };

  const rebasedError = Math.abs(browserDuration - normalizedDuration);
  const originalError = Math.abs(
    browserDuration - (normalizedDuration + sourceOffset),
  );
  const useOriginal = originalError < rebasedError;
  return {
    duration: normalizedDuration,
    offset: useOriginal ? sourceOffset : 0,
    aligned: Math.min(originalError, rebasedError) <= 0.15,
  };
}
