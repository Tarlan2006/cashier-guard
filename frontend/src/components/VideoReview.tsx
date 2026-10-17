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

export type VideoHandle = {
  seek: (seconds: number) => void;
  playContext: (seconds: number) => void;
};
type Props = {
  file: File;
  events: Violation[];
  activeEvent: number;
  onSelect: (index: number) => void;
  onRemove: () => void;
  disabled: boolean;
};

export const VideoReview = forwardRef<VideoHandle, Props>(function VideoReview(
  { file, events, activeEvent, onSelect, onRemove, disabled },
  ref,
) {
  const video = useRef<HTMLVideoElement>(null);
  const clipEnd = useRef<number | null>(null);
  const [url, setUrl] = useState("");
  const [duration, setDuration] = useState(0);
  const [position, setPosition] = useState(0);
  const [unplayable, setUnplayable] = useState(false);
  const [clipLabel, setClipLabel] = useState("");
  useEffect(() => {
    const objectUrl = URL.createObjectURL(file);
    setUrl(objectUrl);
    setDuration(0);
    setPosition(0);
    setUnplayable(false);
    setClipLabel("");
    clipEnd.current = null;
    return () => URL.revokeObjectURL(objectUrl);
  }, [file]);
  function seek(seconds: number) {
    if (!video.current || unplayable || !duration) return;
    video.current.pause();
    clipEnd.current = null;
    setClipLabel("");
    video.current.currentTime = Math.max(0, Math.min(seconds, duration));
    setPosition(video.current.currentTime);
    video.current.scrollIntoView({
      behavior: scrollBehavior(),
      block: "center",
    });
  }
  function playContext(seconds: number) {
    if (!video.current || unplayable || !duration) return;
    const start = Math.max(0, seconds - 3),
      end = Math.min(duration, seconds + 3);
    clipEnd.current = end;
    video.current.currentTime = start;
    setClipLabel(`${timecode(start)} — ${timecode(end)}`);
    video.current.scrollIntoView({
      behavior: scrollBehavior(),
      block: "center",
    });
    void video.current
      .play()
      .catch(() => setClipLabel("Нажмите воспроизведение в плеере."));
  }
  useImperativeHandle(ref, () => ({ seek, playContext }));
  return (
    <div className="selected-file">
      <div className="video-wrap">
        <video
          ref={video}
          src={url || undefined}
          controls
          muted
          playsInline
          preload="metadata"
          aria-label="Предпросмотр загруженного видео"
          onLoadedMetadata={(e) =>
            setDuration(
              Number.isFinite(e.currentTarget.duration)
                ? e.currentTarget.duration
                : 0,
            )
          }
          onError={() => setUnplayable(true)}
          onTimeUpdate={(e) => {
            const current = e.currentTarget.currentTime;
            setPosition(current);
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
          Браузер не воспроизводит этот кодек. Проверка файла и просмотр кадров
          остаются доступны.
        </p>
      )}
      {duration > 0 && !unplayable && (
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
                    className={index === activeEvent ? "active" : ""}
                    aria-label={`Событие ${index + 1}, ${timecode(event.timecode_sec)}`}
                    title={`${index + 1} · ${timecode(event.timecode_sec)}`}
                    onClick={() => {
                      onSelect(index);
                      seek(event.timecode_sec);
                    }}
                  >
                    {index + 1}
                  </button>
                ))}
              </div>
              <div className="timeline-events">
                {events.map((event, index) => (
                  <button
                    key={index}
                    aria-pressed={index === activeEvent}
                    onClick={() => {
                      onSelect(index);
                      seek(event.timecode_sec);
                    }}
                  >
                    {index + 1} · {timecode(event.timecode_sec)}
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
