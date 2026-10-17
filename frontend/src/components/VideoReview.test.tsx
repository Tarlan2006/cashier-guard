import { createRef } from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { VideoReview, type VideoHandle } from "./VideoReview";

beforeEach(() => {
  vi.stubGlobal(
    "URL",
    Object.assign(URL, {
      createObjectURL: vi.fn(() => "blob:timeline-test"),
      revokeObjectURL: vi.fn(),
    }),
  );
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: true })),
  );
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function preview(
  browserDuration: number,
  normalizedDuration: number,
  sourceTimeOffset: number,
  initialPosition = 0,
) {
  const ref = createRef<VideoHandle>();
  const availability = vi.fn();
  render(
    <VideoReview
      ref={ref}
      file={new File(["fixture"], "synthetic.mp4")}
      events={[]}
      activeEvent={0}
      normalizedDuration={normalizedDuration}
      sourceTimeOffset={sourceTimeOffset}
      onSelect={vi.fn()}
      onRemove={vi.fn()}
      onPreviewAvailabilityChange={availability}
      disabled={false}
    />,
  );
  const video = screen.getByLabelText(
    "Предпросмотр загруженного видео",
  ) as HTMLVideoElement;
  Object.defineProperty(video, "duration", {
    value: browserDuration,
    configurable: true,
  });
  video.currentTime = initialPosition;
  fireEvent.loadedMetadata(video);
  return { ref, video, availability };
}

it("translates event seek, context and displayed position to the raw source timeline", () => {
  const { ref, video } = preview(6.266667, 1.3, 5, 5);
  act(() => ref.current?.seek(0.5));
  expect(video.currentTime).toBe(5.5);
  expect(
    (screen.getByLabelText("Позиция в видео") as HTMLInputElement).value,
  ).toBe("0.5");
  expect(screen.getByText("00:00.500")).toBeTruthy();
  act(() => ref.current?.playContext(0.5));
  expect(video.currentTime).toBe(5);
  expect(screen.getByText("Фрагмент: 00:00.000 — 00:01.300")).toBeTruthy();
  video.currentTime = 5.8;
  fireEvent.timeUpdate(video);
  expect(screen.getByText("00:00.800")).toBeTruthy();
});

it("uses zero offset when the browser has already rebased its timeline", () => {
  const { ref, video } = preview(1.3, 1.3, 5);
  act(() => ref.current?.seek(0.5));
  expect(video.currentTime).toBe(0.5);
});

it("updates the mapping when Chrome corrects duration after loadedmetadata", () => {
  const { ref, video } = preview(1.3, 1.3, 5);
  Object.defineProperty(video, "duration", {
    value: 6.266667,
    configurable: true,
  });
  fireEvent.durationChange(video);
  act(() => ref.current?.seek(0.5));
  expect(video.currentTime).toBe(5.5);
});

it("retains native preview but disables uncertain event navigation", () => {
  const { ref, video, availability } = preview(9, 12, 5);
  expect(
    screen.getByText(/нельзя подтвердить точное соответствие времени/),
  ).toBeTruthy();
  expect(screen.queryByLabelText("Позиция в видео")).toBeNull();
  expect(video.controls).toBe(true);
  expect(availability).toHaveBeenLastCalledWith(false);
  act(() => ref.current?.seek(2));
  expect(video.currentTime).toBe(0);
});

it("does not subtract a delayed first video frame from the source timeline", () => {
  const { ref, video } = preview(12, 12, 0, 2);
  expect(screen.getByText("00:02.000")).toBeTruthy();
  act(() => ref.current?.seek(3));
  expect(video.currentTime).toBe(3);
});
