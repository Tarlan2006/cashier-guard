import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { AlertCircle, FileVideo2, Play, X } from "lucide-react";
import { scrollBehavior, timecode } from "../api";
import type { Violation } from "../api";
import { resolveVideoTimeline } from "../videoTimeline";
import { getEventAssessment } from "../assessment";
import { AssessmentIcon } from "./AssessmentBadge";

export type VideoHandle = {
  seek: (seconds: number) => void;
  playContext: (seconds: number) => void;
};
type Props = {
  file: File;
  events: Violation[];
  activeEvent: number;
  normalizedDuration?: number | null;
  sourceTimeOffset?: number | null;
  onSelect: (index: number) => void;
  onRemove: () => void;
  onPreviewAvailabilityChange: (available: boolean) => void;
  disabled: boolean;
};

export const VideoReview = forwardRef<VideoHandle, Props>(function VideoReview(
  {
    file,
    events,
    activeEvent,
    normalizedDuration,
    sourceTimeOffset,
    onSelect,
    onRemove,
    onPreviewAvailabilityChange,
    disabled,
  },
  ref,
) {
  const video = useRef<HTMLVideoElement>(null);
  const clipEnd = useRef<number | null>(null);
  const [url, setUrl] = useState("");
  const [browserDuration, setBrowserDuration] = useState(0);
  const [nativePosition, setNativePosition] = useState(0);
  const [unplayable, setUnplayable] = useState(false);
  const [clipLabel, setClipLabel] = useState("");
  const timeline = resolveVideoTimeline(
    browserDuration,
    normalizedDuration,
    sourceTimeOffset,
  );
  const duration = timeline.duration;
  const position = Math.max(0, nativePosition - timeline.offset);
  useEffect(() => {
    onPreviewAvailabilityChange(!unplayable && timeline.aligned);
  }, [unplayable, timeline.aligned, onPreviewAvailabilityChange]);
  useEffect(() => {
    const objectUrl = URL.createObjectURL(file);
    setUrl(objectUrl);
    setBrowserDuration(0);
    setNativePosition(0);
    setUnplayable(false);
    onPreviewAvailabilityChange(false);
    setClipLabel("");
    clipEnd.current = null;
    return () => URL.revokeObjectURL(objectUrl);
  }, [file, onPreviewAvailabilityChange]);
  function seek(seconds: number) {
    if (!video.current || unplayable || !duration || !timeline.aligned) return;
    video.current.pause();
    clipEnd.current = null;
    setClipLabel("");
    video.current.currentTime =
      Math.max(0, Math.min(seconds, duration)) + timeline.offset;
    setNativePosition(video.current.currentTime);
    video.current.scrollIntoView({
      behavior: scrollBehavior(),
      block: "center",
    });
  }
  function playContext(seconds: number) {
    if (!video.current || unplayable || !duration || !timeline.aligned) return;
    const start = Math.max(0, seconds - 3),
      end = Math.min(duration, seconds + 3);
    clipEnd.current = end + timeline.offset;
    video.current.currentTime = start + timeline.offset;
    setClipLabel(`${timecode(start)} — ${timecode(end)}`);
    video.current.scrollIntoView({
      behavior: scrollBehavior(),
      block: "center",
    });
    void video.current
      .play()
      .catch(() => setClipLabel("Нажмите воспроизведение в плеере."));
  }
  function updateMediaTimeline(element: HTMLVideoElement) {
    setBrowserDuration(
      Number.isFinite(element.duration) ? element.duration : 0,
    );
    setNativePosition(element.currentTime);
  }
  useImperativeHandle(ref, () => ({ seek, playContext }));
  return (
    <div className="selected-file">
      <div
        className="video-wrap"
        style={unplayable ? { display: "none" } : undefined}
      >
        <video
          ref={video}
          src={url || undefined}
          controls
          muted
          playsInline
          preload="metadata"
          aria-label="Предпросмотр загруженного видео"
          onLoadedMetadata={(e) => updateMediaTimeline(e.currentTarget)}
          onDurationChange={(e) => updateMediaTimeline(e.currentTarget)}
          onError={() => {
            setUnplayable(true);
            onPreviewAvailabilityChange(false);
          }}
          onTimeUpdate={(e) => {
            const current = e.currentTarget.currentTime;
            setNativePosition(current);
            if (clipEnd.current !== null && current >= clipEnd.current) {
              e.currentTarget.pause();
              clipEnd.current = null;
            }
          }}
        />
      </div>
      <div className="file-details">
        <FileVideo2 size={22} />
        <div>
          <strong title={file.name}>{file.name}</strong>
          <span>
            {(file.size / 1024 / 1024).toFixed(1)} МБ
            {duration > 0 ? ` · ${timecode(duration)}` : ""}
          </span>
        </div>
        <button
          className="icon-button"
          onClick={onRemove}
          disabled={disabled}
          aria-label="Убрать локальное видео"
        >
          <X size={18} />
        </button>
      </div>
      {unplayable && (
        <p className="video-hint">
          <AlertCircle size={15} />
          Браузер не смог открыть предпросмотр: возможно, он не поддерживает
          контейнер или кодек записи. Это бывает с AVI, MKV и некоторыми MOV.
          Файл можно отправить на анализ — сервер проверит его и преобразует в
          MP4. Кадры результата останутся доступны.
        </p>
      )}
      {browserDuration > 0 && !unplayable && !timeline.aligned && (
        <p className="video-hint">
          <AlertCircle size={15} />
          Временная шкала браузера отличается от обработанного видео. Переходы к
          событиям недоступны: нельзя подтвердить точное соответствие времени.
          Обычный просмотр и кадры результата доступны.
        </p>
      )}
      {duration > 0 && !unplayable && timeline.aligned && (
        <div className="video-timeline">
          <div className="timeline-caption">
            <label htmlFor="video-position">Позиция в видео</label>
            <output htmlFor="video-position">{timecode(position)}</output>
          </div>
          <input
            id="video-position"
            aria-label="Позиция в видео"
            type="range"
            min="0"
            max={duration}
            step="0.001"
            value={Math.min(position, duration)}
            onChange={(e) => seek(Number(e.target.value))}
          />
          {events.length > 0 && (
            <>
              <div
                className="timeline-markers"
                role="group"
                aria-label="Отметки событий на шкале"
              >
                {events.map((event, index) => (
                  <button
                    key={index}
                    style={{
                      left: `${Math.min(100, (event.timecode_sec / duration) * 100)}%`,
                    }}
                    className={`assessment-${getEventAssessment(event).level} ${index === activeEvent ? "active" : ""}`}
                    data-assessment={getEventAssessment(event).level}
                    aria-pressed={index === activeEvent}
                    aria-label={`Событие ${index + 1}, ${timecode(event.timecode_sec)}, ${getEventAssessment(event).label}`}
                    title={`${index + 1} · ${timecode(event.timecode_sec)} · ${getEventAssessment(event).label}`}
                    onClick={() => {
                      onSelect(index);
                      seek(event.timecode_sec);
                    }}
                  >
                    <AssessmentIcon
                      level={getEventAssessment(event).level}
                      size={14}
                    />
                    {index + 1}
                  </button>
                ))}
              </div>
              <div className="timeline-events">
                {events.map((event, index) => (
                  <button
                    key={index}
                    className={`assessment-${getEventAssessment(event).level}`}
                    data-assessment={getEventAssessment(event).level}
                    aria-pressed={index === activeEvent}
                    onClick={() => {
                      onSelect(index);
                      seek(event.timecode_sec);
                    }}
                  >
                    <AssessmentIcon
                      level={getEventAssessment(event).level}
                      size={16}
                    />
                    <span>
                      {index + 1} · {timecode(event.timecode_sec)} ·{" "}
                      {getEventAssessment(event).label}
                    </span>
                  </button>
                ))}
              </div>
              <button
                className="text-button context-button"
                onClick={() =>
                  playContext(
                    events[activeEvent]?.timecode_sec ?? events[0].timecode_sec,
                  )
                }
              >
                <Play size={15} />
                Посмотреть ±3 секунды
              </button>
            </>
          )}
          {clipLabel && (
            <p className="clip-label" role="status">
              Фрагмент: {clipLabel}
            </p>
          )}
        </div>
      )}
    </div>
  );
});
