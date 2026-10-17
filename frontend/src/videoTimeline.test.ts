import { describe, expect, it } from "vitest";
import { resolveVideoTimeline } from "./videoTimeline";

describe("browser and normalized video timeline mapping", () => {
  it("retains the source preview timeline before a job or for old results", () => {
    expect(resolveVideoTimeline(12)).toEqual({
      duration: 12,
      offset: 0,
      aligned: true,
    });
    expect(resolveVideoTimeline(12, 12, null)).toEqual({
      duration: 12,
      offset: 0,
      aligned: true,
    });
  });
  it("uses the normalized duration directly for an origin of zero", () => {
    expect(resolveVideoTimeline(12.03, 12, 0)).toEqual({
      duration: 12,
      offset: 0,
      aligned: true,
    });
  });
  it("maps the raw positive origin allowing final-frame rounding", () => {
    expect(resolveVideoTimeline(6.266667, 1.3, 5)).toEqual({
      duration: 1.3,
      offset: 5,
      aligned: true,
    });
  });
  it("does not add the source origin when the browser has rebased it", () => {
    expect(resolveVideoTimeline(1.266667, 1.3, 5)).toEqual({
      duration: 1.3,
      offset: 0,
      aligned: true,
    });
  });
  it("supports a signed negative source origin", () => {
    expect(resolveVideoTimeline(11.5, 12, -0.5)).toEqual({
      duration: 12,
      offset: -0.5,
      aligned: true,
    });
    expect(resolveVideoTimeline(12, 12, -0.5)).toEqual({
      duration: 12,
      offset: 0,
      aligned: true,
    });
  });
  it("disables event navigation when neither duration matches", () => {
    expect(resolveVideoTimeline(9, 12, 5).aligned).toBe(false);
  });
  it("does not infer the origin from a delayed first video frame", () => {
    expect(resolveVideoTimeline(12, 12, 0)).toEqual({
      duration: 12,
      offset: 0,
      aligned: true,
    });
  });
  it("requires valid loaded metadata", () => {
    expect(resolveVideoTimeline(0, 12, 5).aligned).toBe(false);
    expect(resolveVideoTimeline(Infinity, 12, 5).aligned).toBe(false);
    expect(resolveVideoTimeline(12, 12, NaN).aligned).toBe(false);
  });
});
