"""Render local contact sheets with person boxes, track IDs and positional roles.

Example (reuse facts without running a detector)::

    python scripts/debug_perception.py data/open/videos/X-1.mov --facts debug/1/facts.json
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.pipeline.video import VideoReader

LOG = logging.getLogger(__name__)


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _color(identifier: int) -> tuple[int, int, int]:
    palette = (
        (0, 220, 150),
        (255, 190, 30),
        (70, 185, 255),
        (245, 100, 220),
        (230, 120, 50),
    )
    return palette[identifier % len(palette)]


def _box_pixels(box: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    if len(box) != 4 or not all(math.isfinite(float(value)) for value in box):
        raise ValueError("Debug boxes must be finite normalized xyxy")
    x1, y1, x2, y2 = (float(value) for value in box)
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        raise ValueError("Debug boxes must be normalized ordered xyxy in [0,1]")
    return (
        round(x1 * (width - 1)),
        round(y1 * (height - 1)),
        round(x2 * (width - 1)),
        round(y2 * (height - 1)),
    )


def _label(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    text: str,
    color: tuple[int, int, int],
    font: ImageFont.ImageFont,
    width: int,
) -> None:
    left, top = position
    extent = draw.textbbox((0, 0), text, font=font)
    left = max(2, min(left, width - (extent[2] - extent[0]) - 3))
    box = draw.textbbox((left, top), text, font=font)
    draw.rectangle((box[0] - 2, box[1] - 2, box[2] + 2, box[3] + 2), fill=(15, 20, 28))
    draw.text((left, top), text, fill=color, font=font)


def _dashed_rectangle(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    color: tuple[int, int, int],
    *,
    width: int = 2,
    dash: int = 7,
) -> None:
    """Draw a real dashed outline so reflected tracks differ without color."""
    x1, y1, x2, y2 = box
    for left in range(x1, x2 + 1, dash * 2):
        right = min(left + dash, x2)
        draw.line((left, y1, right, y1), fill=color, width=width)
        draw.line((left, y2, right, y2), fill=color, width=width)
    for top in range(y1, y2 + 1, dash * 2):
        bottom = min(top + dash, y2)
        draw.line((x1, top, x1, bottom), fill=color, width=width)
        draw.line((x2, top, x2, bottom), fill=color, width=width)


def _reflection_reason(person: dict[str, Any]) -> str:
    reason = person.get(
        "reflection_reason", person.get("reflection_reasons", "reflection_filter")
    )
    if isinstance(reason, list):
        reason = "; ".join(str(item) for item in reason)
    return str(reason)


def create_contact_sheet(
    video_path: str | Path,
    facts: dict[str, Any],
    output_path: str | Path | None = None,
    *,
    max_frames: int = 12,
    columns: int = 4,
    thumb_width: int = 320,
) -> Path:
    """Save one JPEG contact sheet; no inference, labels or network accesses."""
    if min(max_frames, columns, thumb_width) <= 0:
        raise ValueError("Sheet dimensions and max_frames must be positive")
    video_path = Path(video_path)
    frames = facts.get("frames", [])
    if not frames:
        raise ValueError("No facts frames to render")
    chosen = np.unique(
        np.round(np.linspace(0, len(frames) - 1, min(max_frames, len(frames)))).astype(
            int
        )
    )
    output = (
        Path(output_path)
        if output_path
        else Path("debug") / video_path.stem / "contact.jpg"
    )
    title_font, label_font = _font(17), _font(13)
    cells: list[Image.Image] = []
    with VideoReader(video_path) as reader:
        meta = reader.metadata
        known_meta = facts.get("video", {})
        if known_meta.get("name", video_path.name) != video_path.name:
            raise ValueError("Facts describe a different video filename")
        for dimension in ("width", "height"):
            if dimension in known_meta and known_meta[dimension] != getattr(
                meta, dimension
            ):
                raise ValueError("Facts dimensions do not match this oriented video")
        thumb_height = max(1, round(meta.height * thumb_width / meta.width))
        geometry = facts.get("config", {}).get("counter_geometry")
        for index in chosen:
            row = frames[int(index)]
            source_time = float(row.get("actual_timestamp_sec", row["timestamp_sec"]))
            sample = reader.read_at(source_time)
            rgb = cv2.cvtColor(sample.frame_bgr, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb).resize(
                (thumb_width, thumb_height), Image.Resampling.LANCZOS
            )
            draw = ImageDraw.Draw(image)
            if geometry and geometry.get("line"):
                points = [
                    (round(x * (thumb_width - 1)), round(y * (thumb_height - 1)))
                    for x, y in geometry["line"]
                ]
                draw.line(points, fill=(255, 255, 255), width=3)
            for person in row.get("persons", []):
                box = _box_pixels(person["bbox"], thumb_width, thumb_height)
                color = _color(int(person["id"]))
                reflected = bool(person.get("is_reflection", False))
                if reflected:
                    _dashed_rectangle(draw, box, color)
                    text = f"#{person['id']} REFLECTION {float(person.get('confidence', 0)):.2f}"
                else:
                    draw.rectangle(box, outline=color, width=3)
                    role = str(person.get("role", "unknown"))
                    state = (
                        "UNCERTAIN "
                        if person.get("uncertain", False)
                        else "TENTATIVE " if not person.get("counted", True) else ""
                    )
                    text = f"#{person['id']} {state}{role} {float(person.get('confidence', 0)):.2f}"
                _label(
                    draw,
                    (box[0] + 2, max(0, box[1] - 17)),
                    text,
                    color,
                    label_font,
                    thumb_width,
                )
                if reflected:
                    reason = _reflection_reason(person)
                    if len(reason) > 36:
                        reason = reason[:33] + "..."
                    _label(
                        draw,
                        (box[0] + 2, min(thumb_height - 16, box[1] + 3)),
                        reason,
                        color,
                        label_font,
                        thumb_width,
                    )
                elif "cashier_prob" in person:
                    probabilities = f"Pc={person['cashier_prob']:.2f} Pl={person['client_prob']:.2f}"
                    _label(
                        draw,
                        (box[0] + 2, min(thumb_height - 16, box[1] + 3)),
                        probabilities,
                        color,
                        label_font,
                        thumb_width,
                    )
            for item in row.get("objects", []):
                if item["class"] == "counter_machine" and row.get("counter_machine"):
                    continue
                if item["class"] in {
                    "chair",
                    "diningtable",
                    "bench",
                    "bed",
                    "toilet",
                } and not item.get("fixture", False):
                    continue
                box = _box_pixels(item["bbox"], thumb_width, thumb_height)
                draw.rectangle(box, outline=(200, 200, 200), width=2)
                name = str(item.get("name", item["class"]))
                if item.get("is_fixture", item.get("fixture", False)):
                    name = "fixture: " + name
                _label(
                    draw,
                    (box[0] + 2, max(0, box[1] - 17)),
                    name,
                    (220, 220, 220),
                    label_font,
                    thumb_width,
                )
            machines = row.get("counter_machine")
            machines = (
                machines
                if isinstance(machines, list)
                else [machines] if machines else []
            )
            for item in machines:
                if not isinstance(item, dict):
                    continue
                box = _box_pixels(item["bbox"], thumb_width, thumb_height)
                draw.rectangle(box, outline=(255, 255, 255), width=3)
                _label(
                    draw,
                    (box[0] + 2, max(0, box[1] - 17)),
                    "counter_machine",
                    (255, 255, 255),
                    label_font,
                    thumb_width,
                )
            cell = Image.new("RGB", (thumb_width, thumb_height + 56), (25, 30, 38))
            cell.paste(image, (0, 0))
            caption = ImageDraw.Draw(cell)
            caption.text(
                (6, thumb_height + 4),
                f"grid {float(row['timestamp_sec']):.2f}s | source {sample.actual_timestamp_sec:.2f}s",
                fill="white",
                font=label_font,
            )
            counter = row.get("counter", {})
            persons = row.get("persons", [])
            people_count = sum(
                not person.get("is_reflection", False) and person.get("counted", True)
                for person in persons
            )
            reflection_count = sum(
                person.get("is_reflection", False) for person in persons
            )
            uncertain = sum(
                person.get("uncertain", False) and person.get("counted", True)
                for person in persons
            )
            pending = sum(
                not person.get("is_reflection", False)
                and not person.get("counted", True)
                for person in persons
            )
            caption.text(
                (6, thumb_height + 24),
                f"people {people_count} ({uncertain}?) | reflections {reflection_count} | pending {pending}",
                fill=(200, 210, 225),
                font=label_font,
            )
            cells.append(cell)
    columns = min(columns, len(cells))
    rows = math.ceil(len(cells) / columns)
    gap, title_height = 8, 58
    cell_width, cell_height = cells[0].size
    sheet = Image.new(
        "RGB",
        (
            columns * (cell_width + gap) + gap,
            rows * (cell_height + gap) + gap + title_height,
        ),
        (10, 15, 23),
    )
    draw = ImageDraw.Draw(sheet)
    draw.text((gap, 8), video_path.name, fill="white", font=title_font)
    draw.text(
        (gap, 32),
        "Solid: people | dashed: reflections (excluded) | roles: positional/temporal candidates",
        fill=(200, 210, 225),
        font=label_font,
    )
    for index, image in enumerate(cells):
        sheet.paste(
            image,
            (
                gap + index % columns * (cell_width + gap),
                title_height + gap + index // columns * (cell_height + gap),
            ),
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=90)
    LOG.info("Saved %s (%d frames)", output, len(cells))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("videos", nargs="+", type=Path)
    parser.add_argument(
        "--facts", type=Path, help="Reuse an existing facts.json (one input video)"
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("debug"))
    parser.add_argument("--max-frames", type=int, default=12)
    parser.add_argument("--columns", type=int, default=4)
    parser.add_argument("--thumb-width", type=int, default=320)
    args = parser.parse_args()
    if args.facts and len(args.videos) != 1:
        parser.error("--facts requires exactly one video")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    for video in args.videos:
        destination = args.output_dir / video.stem
        if args.facts:
            with args.facts.open(encoding="utf-8") as stream:
                facts = json.load(stream)
        else:
            from backend.pipeline.perception import load_config, perceive_video

            facts = perceive_video(
                video, load_config(args.config), destination / "facts.json"
            )
        output = create_contact_sheet(
            video,
            facts,
            destination / "contact.jpg",
            max_frames=args.max_frames,
            columns=args.columns,
            thumb_width=args.thumb_width,
        )
        print(output)


if __name__ == "__main__":
    main()
