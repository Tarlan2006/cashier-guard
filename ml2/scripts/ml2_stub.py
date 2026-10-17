"""Loopback transport-test stub for participant 2's /match; no AI model."""

from fastapi import FastAPI, HTTPException

app = FastAPI(title="Local integration stub; not a rule verifier")


@app.get("/health")
def health():
    return dict(status="ok", stub=True)


@app.post("/match")
def match(payload: dict):
    events = payload.get("events", [])
    if not events:
        return dict(verdict="no_violation", violations=[])
    rules = {rule["id"]: rule for rule in payload.get("rules", [])}
    violations = []
    for event in events:
        rule_id = event["id"].split(":", 1)[0]
        if rule_id not in rules:
            raise HTTPException(
                422, "Stub has no approved catalog match for this observation"
            )
        violations.append(
            dict(
                type=rule_id,
                rule_id=rule_id,
                timecode_sec=event["start_sec"],
                description=event["description"],
                evidence_frames=event["evidence_frames"],
            )
        )
    return dict(verdict="violation", violations=violations)
