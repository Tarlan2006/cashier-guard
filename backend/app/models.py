from typing import Literal
import base64

from pydantic import BaseModel, Field, model_validator, field_validator


class EvidenceFrame(BaseModel):
    timestamp_sec: float = Field(ge=0)
    image_base64: str = Field(min_length=4, max_length=4_000_000)

    @field_validator("image_base64")
    @classmethod
    def jpeg_only(cls, value: str) -> str:
        try:
            data = base64.b64decode(value, validate=True)
        except ValueError as error:
            raise ValueError("Evidence must be valid base64") from error
        if not data.startswith(b"\xff\xd8\xff") or not data.endswith(b"\xff\xd9"):
            raise ValueError("Evidence must be a JPEG image")
        return value


class Rule(BaseModel):
    id: str
    title: str
    visual_signs: list[str]
    document: str
    section: str
    url: str


class Observation(BaseModel):
    id: str
    start_sec: float = Field(ge=0)
    end_sec: float = Field(ge=0)
    description: str = Field(min_length=1)
    evidence_frames: list[EvidenceFrame] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def ordered_interval(self):
        if self.end_sec < self.start_sec:
            raise ValueError("end_sec must be >= start_sec")
        return self


class Observations(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    events: list[Observation] = Field(default_factory=list)


class Violation(BaseModel):
    type: str = Field(min_length=1)
    timecode_sec: float = Field(ge=0)
    description: str = Field(min_length=1)
    evidence_frames: list[EvidenceFrame] = Field(min_length=1, max_length=3)
    rule_id: str | None = None
    rule: Rule | None = None


class AnalysisResult(BaseModel):
    verdict: Literal["violation", "no_violation"]
    violations: list[Violation] = Field(default_factory=list)

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
    duration_sec: float | None = None
    verdict: Literal["violation", "no_violation"] | None = None
    violations: list[Violation] = Field(default_factory=list)
    error: str | None = None

