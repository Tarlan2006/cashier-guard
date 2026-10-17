"""Open video 14 twice, video stream only, and a real outer API benchmark."""

from pathlib import Path
import json
import sys
import time
import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.pipeline.video import VideoReader
from backend.pipeline.analyze import analyze_report


def main():
    manifest = json.loads(
        (ROOT / "cache/all40/stage1/manifest.json").read_text(encoding="utf-8")
    )
    source = Path(next(r["path"] for r in manifest if r["num"] == 14))
    assert source.resolve().is_relative_to((ROOT / "data/open").resolve())
    target = ROOT / "cache/v6/open14_twice.mov"
    if not target.exists():
        with VideoReader(source) as reader:
            m = reader.metadata
            writer = cv2.VideoWriter(
                str(target), cv2.VideoWriter_fourcc(*"mp4v"), m.fps, (m.width, m.height)
            )
            if not writer.isOpened():
                raise RuntimeError("Cannot create local benchmark video")
            try:
                for _ in range(2):
                    cap = cv2.VideoCapture(str(source))
                    cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 0)
                    try:
                        while True:
                            ok, frame = cap.read()
                            if not ok:
                                break
                            writer.write(reader._orient(frame))
                    finally:
                        cap.release()
            finally:
                writer.release()
    with VideoReader(target) as reader:
        duration = reader.metadata.duration_sec
    started = time.perf_counter()
    report = analyze_report(target)
    report.update(
        input_duration_sec=duration,
        wall_elapsed_sec=time.perf_counter() - started,
        cache_used=False,
        source="open14_twice; reencoded video only, no audio",
    )
    (ROOT / "cache/v6/long_benchmark.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "events"},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
