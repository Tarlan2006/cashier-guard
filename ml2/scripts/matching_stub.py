"""Explicit loopback transport stub; no semantic matching or legal verification.

Run: python -m uvicorn scripts.matching_stub:app --host 127.0.0.1 --port 8002
Only the rule_id encoded by the ML1 adapter as rule_id:index:seconds is copied.
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from scripts.check_events import ContractError, validate_matching_request, validate_result

app = FastAPI(title='Matching TRANSPORT STUB (not a model or rule verifier)')


@app.get('/health')
def health() -> dict:
    return dict(status='ok', stub=True, semantic_matching=False)


@app.post('/match')
def match(payload: dict) -> JSONResponse:
    try:
        catalog = validate_matching_request(payload)
        violations = []
        for event in payload['events']:
            parts = event['id'].rsplit(':', 2)
            if len(parts) != 3 or parts[0] not in catalog or not parts[1].isdigit():
                raise ContractError('Observation does not encode a rule_id from the supplied catalog')
            rule_id = parts[0]
            violations.append(dict(type=catalog[rule_id]['title'], rule_id=rule_id,
                timecode_sec=event['start_sec'], description=event['description'],
                evidence_frames=event['evidence_frames'], assessment='needs_review',
                assessment_reason='Transport stub copied an explicit rule_id; no semantic or legal verification.'))
        result = dict(verdict='violation' if violations else 'no_violation', violations=violations)
        validate_result(result, payload['duration_sec'], payload['rules'])
        return JSONResponse(result, headers={'X-Matching-Stub': 'true'})
    except ContractError as error:
        raise HTTPException(422, str(error)) from None
