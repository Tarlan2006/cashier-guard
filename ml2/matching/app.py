"""ML2 contract service: explicit rule IDs only, no semantic/legal inference."""
from __future__ import annotations

import math
from pathlib import Path
import sys

from fastapi import FastAPI, HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_events import ContractError, validate_matching_request, validate_result

ASSESSMENT_REASON = "сопоставление только по явному rule_id, без семантики и юридической проверки"
app = FastAPI(title="Cashier Guard local explicit-rule matching (ML2)")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "semantic_matching": False}


def explicit_rule(event: dict, catalog: dict, duration: float) -> str:
    parts = event["id"].rsplit(":", 2)
    if len(parts) != 3:
        raise ContractError("Observation id must encode rule_id:index:seconds")
    rule_id, index, encoded_seconds = parts
    if rule_id not in catalog:
        raise ContractError("Observation rule_id is not in the supplied catalog")
    if not index or not index.isascii() or not index.isdecimal():
        raise ContractError("Observation index must be a nonnegative integer")
    try:
        timestamp = float(encoded_seconds)
    except ValueError:
        raise ContractError("Observation id must contain numeric seconds") from None
    if (not math.isfinite(timestamp) or timestamp < 0 or timestamp >= duration
            or not math.isclose(timestamp, event["start_sec"], rel_tol=0, abs_tol=0.00051)):
        # ML1 rounds its start timestamp to three decimal places in the ID.
        raise ContractError("Observation id timestamp disagrees with start_sec or duration")
    return rule_id


@app.post("/match")
def match(payload: dict) -> dict:
    try:
        catalog = validate_matching_request(payload)
        violations = []
        for event in payload["events"]:
            rule_id = explicit_rule(event, catalog, payload["duration_sec"])
            violations.append(dict(type=catalog[rule_id]["title"], rule_id=rule_id,
                timecode_sec=event["start_sec"], description=event["description"],
                evidence_frames=event["evidence_frames"], assessment="needs_review",
                assessment_reason=ASSESSMENT_REASON))
        result = dict(verdict="violation" if violations else "no_violation", violations=violations)
        validate_result(result, payload["duration_sec"], payload["rules"])
        return result
    except ContractError as exc:
        raise HTTPException(422, str(exc)) from None
