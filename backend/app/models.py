"""Public API and local ML contracts. Keep exported schemas in contracts/ in sync."""
import base64
import binascii
import warnings
from io import BytesIO
from typing import Annotated, Literal
from urllib.parse import urlsplit

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8_000)]
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]
MAX_EVIDENCE_PIXELS = 8_000_000
MAX_EVIDENCE_DIMENSION = 8_192


class EvidenceFrame(BaseModel):
    timestamp_sec: Seconds
    image_base64: str = Field(min_length=4, max_length=4_000_000)

    @field_validator("image_base64")
    @classmethod
    def jpeg_only(cls, value: str) -> str:
        try:
            data = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError("Evidence must be valid base64") from error
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(data)) as image:
                    width, height = image.size
                    if image.format != "JPEG":
                        raise ValueError("Evidence must be a JPEG image")
                    if width * height > MAX_EVIDENCE_PIXELS or max(width, height) > MAX_EVIDENCE_DIMENSION:
                        raise ValueError("Evidence JPEG dimensions exceed the limit")
                    image.verify()
                # verify() does not decode JPEG data or reject every truncated file.
                with Image.open(BytesIO(data)) as image:
                    image.load()
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            raise ValueError("Evidence must be a complete decodable JPEG within the image limits") from error
        return value


class Rule(BaseModel):
    id: Identifier
    title: NonBlank
    visual_signs: list[NonBlank] = Field(min_length=1, max_length=100)
    document: NonBlank
    section: NonBlank
    url: str = Field(min_length=1, max_length=2_048, pattern=r"^https?://", json_schema_extra={"format": "uri"})
    is_demo: bool = False

    @field_validator("url")
    @classmethod
    def source_url(cls, value: str) -> str:
        if value != value.strip() or any(character.isspace() or ord(character) < 32 for character in value):
            raise ValueError("Rule source must be an absolute HTTP(S) URL")
        try:
            parsed = urlsplit(value)
            valid = parsed.scheme in {"http", "https"} and parsed.hostname and parsed.port != 0
        except ValueError as error:
            raise ValueError("Invalid rule source URL") from error
        if not valid or parsed.username or parsed.password:
            raise ValueError("Rule source must be an absolute HTTP(S) URL without credentials")
        return value


class RuleCatalog(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    rules: list[Rule] = Field(max_length=5_000)

    @model_validator(mode="after")
    def unique_rule_ids(self):
        ids = [rule.id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("Rule IDs must be unique")
        return self


class Observation(BaseModel):
    id: Identifier
    start_sec: Seconds
    end_sec: Seconds
    description: NonBlank
    evidence_frames: list[EvidenceFrame] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def ordered_interval(self):
        if self.end_sec < self.start_sec:
            raise ValueError("end_sec must be >= start_sec")
        return self


class Observations(BaseModel):
    # No defaults: {}, missing events, or an unknown version are ML failures.
    schema_version: Literal["1.0"]
    events: list[Observation] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_event_ids(self):
        ids = [event.id for event in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError("Observation IDs must be unique")
        return self


class MatchingRequest(Observations):
    duration_sec: float = Field(gt=0, allow_inf_nan=False)
    rules: list[Rule] = Field(min_length=1, max_length=5_000)


class Violation(BaseModel):
    model_config = ConfigDict(json_schema_extra={"allOf": [{
        "if": {"properties": {"assessment": {"const": "strong_evidence"}}, "required": ["assessment"]},
        "then": {"required": ["assessment_reason"], "properties": {"assessment_reason": {"type": "string", "minLength": 1, "pattern": r"\S"}}},
    }]})
    type: NonBlank
    timecode_sec: Seconds
    description: NonBlank
    evidence_frames: list[EvidenceFrame] = Field(min_length=1, max_length=3)
    rule_id: Identifier | None = None
    rule: Rule | None = None
    assessment: Literal["strong_evidence", "needs_review"] | None = Field(
        default=None,
        description="ML2 evidence assessment. Missing/null is legacy: display needs_review without inventing an assessment.",
    )
    assessment_reason: NonBlank | None = Field(
        default=None, description="ML2 explanation of the assessment. Required for strong_evidence; never a confidence percentage.",
    )

    @model_validator(mode="after")
    def explained_strong_evidence(self):
        if self.assessment == "strong_evidence" and self.assessment_reason is None:
            raise ValueError("strong_evidence requires assessment_reason")
        return self


class AnalysisResult(BaseModel):
    verdict: Literal["violation", "no_violation"]
    violations: list[Violation] = Field(max_length=100)

    @model_validator(mode="after")
    def consistent_verdict(self):
        if (self.verdict == "violation") != bool(self.violations):
            raise ValueError("verdict must agree with violations")
        return self


class JobResponse(BaseModel):
    job_id: str
    status: Literal["processing", "done", "failed"]
    stage: Literal["queued", "preparing", "analyzing", "matching", "done", "failed"]
    mode: Literal["demo", "live"]
    filename: str
    created_at: str
    duration_sec: Seconds | None = None
    source_time_offset_sec: float | None = Field(
        default=None, allow_inf_nan=False,
        description="Original container timeline origin. Add to normalized event time for source media timestamps; browsers may rebase their playback timeline. Null for older jobs.",
    )
    size_bytes: int | None = Field(default=None, ge=0)
    verdict: Literal["violation", "no_violation"] | None = None
    violations: list[Violation] = Field(default_factory=list)
    error: str | None = None
    error_code: str | None = None
    timings_sec: dict[str, Seconds] = Field(default_factory=dict)
    expires_at: str | None = None
    deadline_at: str | None = None
    demo_scenario: str | None = None
    completed_at: str | None = None

    @model_validator(mode="before")
    @classmethod
    def explicit_completed_result(cls, value):
        if isinstance(value, dict) and value.get("status") == "done" and "violations" not in value:
            raise ValueError("Completed jobs require an explicit violations list")
        return value

    @model_validator(mode="after")
    def consistent_state(self):
        if self.status == "done":
            if self.stage != "done" or self.verdict is None or self.error is not None or self.error_code is not None:
                raise ValueError("Completed jobs must have a result and no error")
            if (self.verdict == "violation") != bool(self.violations):
                raise ValueError("verdict must agree with violations")
            for event in self.violations:
                if self.duration_sec is not None and (event.timecode_sec >= self.duration_sec or any(
                    frame.timestamp_sec >= self.duration_sec for frame in event.evidence_frames
                )):
                    raise ValueError("Event timestamps must be inside the video")
                if self.mode == "live" and event.assessment == "strong_evidence" and (
                    event.rule is None or event.rule.is_demo or event.rule.id.startswith("demo:")
                    or event.rule_id != event.rule.id
                ):
                    raise ValueError("Live strong_evidence requires a checked rule")
        elif self.verdict is not None or self.violations:
            raise ValueError("Incomplete jobs cannot contain a verdict or events")
        elif self.status == "failed" and self.stage != "failed":
            raise ValueError("Failed jobs require failed stage")
        elif self.status == "processing" and self.stage in {"done", "failed"}:
            raise ValueError("Processing jobs require an active stage")
        return self
