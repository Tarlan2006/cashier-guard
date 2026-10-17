"""ML1 contract mapping with real JPEG decoding and bounded response size."""

import base64
from io import BytesIO
import math
import json
from PIL import Image
from backend.schemas import Event


def compact_jpeg(data: bytes, *, max_chars: int = 4_000_000) -> str:
    with Image.open(BytesIO(data)) as original:
        if original.format != "JPEG":
            raise ValueError("Evidence is not JPEG")
        original.load()
        image = original.convert("RGB")
    image.thumbnail((1280, 1280))
    for _ in range(12):
        out = BytesIO()
        image.save(out, format="JPEG", quality=80, optimize=True)
        encoded = base64.b64encode(out.getvalue()).decode("ascii")
        if (
            len(encoded) <= max_chars
            and image.width * image.height <= 8_000_000
            and max(image.size) <= 8192
        ):
            return encoded
        image.thumbnail(
            (max(1, int(image.width * 0.7)), max(1, int(image.height * 0.7)))
        )
    raise ValueError("Evidence cannot fit the contract limit")


def observations(events: list[Event]) -> dict:
    if len(events) > 100:
        raise ValueError("More than 100 events would exceed the ML1 contract")
    count = sum(len(e.frames) for e in events)
    frame_budget = min(4_000_000, 27 * 1024 * 1024 // max(1, count))
    result = []
    for index, event in enumerate(events):
        if not 1 <= len(event.frames) <= 3 or len(event.frames) != len(
            event.frame_timecodes_sec
        ):
            raise ValueError("Each event needs 1-3 timestamped JPEGs")
        if not event.description.strip() or len(event.description) > 8000:
            raise ValueError("Event description is outside contract bounds")
        start = float(event.timecode_sec)
        end = max(
            start,
            float(event.confirmed_at if event.confirmed_at is not None else start),
        )
        if not all(
            math.isfinite(t) and t >= 0
            for t in [start, end, *event.frame_timecodes_sec]
        ):
            raise ValueError("Invalid event or frame timecode")
        identifier = f"{event.rule_id}:{index:03}:{start:.3f}"
        if len(identifier) > 200:
            raise ValueError("Observation identifier is too long")
        result.append(
            dict(
                id=identifier,
                start_sec=start,
                end_sec=end,
                description=event.description,
                evidence_frames=[
                    dict(
                        timestamp_sec=t,
                        image_base64=compact_jpeg(data, max_chars=frame_budget),
                    )
                    for t, data in zip(event.frame_timecodes_sec, event.frames)
                ],
            )
        )
    payload = dict(schema_version="1.0", events=result)
    if (
        len(
            json.dumps(
                payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode("utf-8")
        )
        > 32 * 1024 * 1024
    ):
        raise ValueError("Response exceeds the backend size limit")
    return payload
