"""Small dependency-free contracts for the local analysis API.

``Event.frames`` contains encoded JPEG bytes, not file paths or raw pixels.
The API adapter may call ``to_dict`` to get a JSON-safe base64 representation.
"""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Event:
    """An observation with its actual decoded evidence-frame timestamps."""

    type: str
    rule_id: str
    timecode_sec: float
    description: str
    confidence: float
    frames: list[bytes] = field(default_factory=list)
    frame_timecodes_sec: list[float] = field(default_factory=list)
    first_seen: float | None = None
    confirmed_at: float | None = None

    def __post_init__(self) -> None:
        if not self.type or not self.rule_id or not self.description:
            raise ValueError("Event type, rule_id and description must be nonempty")
        if not math.isfinite(self.timecode_sec) or self.timecode_sec < 0:
            raise ValueError("Event timecode_sec must be finite and nonnegative")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("Event confidence must be in [0, 1]")
        for value in (self.first_seen, self.confirmed_at):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(
                    "Onset/confirmation timestamps must be finite and nonnegative"
                )
        if (
            self.first_seen is not None
            and abs(self.first_seen - self.timecode_sec) > 1e-6
        ):
            raise ValueError("Event timecode must equal first_seen")
        if self.confirmed_at is not None and self.confirmed_at < self.timecode_sec:
            raise ValueError("Confirmation cannot precede event onset")
        if len(self.frames) != len(self.frame_timecodes_sec):
            raise ValueError("Each JPEG must have an actual frame timestamp")
        for jpeg, timestamp in zip(self.frames, self.frame_timecodes_sec):
            if (
                not isinstance(jpeg, bytes)
                or not jpeg.startswith(b"\xff\xd8")
                or not jpeg.endswith(b"\xff\xd9")
            ):
                raise ValueError("Event frames must contain encoded JPEG bytes")
            if not math.isfinite(timestamp) or timestamp < 0:
                raise ValueError(
                    "Evidence frame timestamp must be finite and nonnegative"
                )

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe data; ``frames`` are base64-encoded JPEG strings."""
        return {
            "type": self.type,
            "rule_id": self.rule_id,
            "timecode_sec": self.timecode_sec,
            "description": self.description,
            "confidence": self.confidence,
            "frames": [base64.b64encode(jpeg).decode("ascii") for jpeg in self.frames],
            "frame_timecodes_sec": list(self.frame_timecodes_sec),
            "frames_encoding": "base64/jpeg",
            "first_seen": (
                self.timecode_sec if self.first_seen is None else self.first_seen
            ),
            "confirmed_at": self.confirmed_at,
        }
