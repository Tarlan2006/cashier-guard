"""Validate local ML1/result/job JSON, including JPEG evidence; print no images."""
from __future__ import annotations

import argparse
import base64
import binascii
from io import BytesIO
import json
import math
from pathlib import Path
from urllib.parse import urlsplit
import warnings

import jsonschema
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
MAX_JSON_BYTES = 32 * 1024 * 1024


class ContractError(ValueError):
    """A response cannot be accepted as a successful video result."""


def read_json(path: Path) -> dict:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ContractError('JSON exceeds 32 MiB')
    return json.loads(path.read_text(encoding='utf-8'))


def schema_check(payload: object, name: str) -> None:
    schema = read_json(REPO / 'contracts' / name)
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    error = next(validator.iter_errors(payload), None)
    if error:
        # ValidationError.message may contain an entire base64 image. Do not log it.
        location = '/'.join(map(str, error.absolute_path)) or '<root>'
        raise ContractError(f'Invalid {name} at {location} ({error.validator})')


def seconds(value: object, *, duration: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError('Timestamp must be a number')
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value < 0 or (duration is not None and value >= duration):
        raise ContractError('Timestamp must be finite and inside the video')
    return float(value)


def video_duration(value: object) -> float:
    result = seconds(value)
    if result <= 0:
        raise ContractError('Video duration must be positive')
    return result


def nonblank(value: str) -> None:
    if not value.strip():
        raise ContractError('Identifiers and descriptions must not be blank')


def check_frames(frames: list[dict], duration: float | None) -> None:
    for frame in frames:
        seconds(frame['timestamp_sec'], duration=duration)
        try:
            data = base64.b64decode(frame['image_base64'], validate=True)
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(BytesIO(data)) as image:
                    if (image.format != 'JPEG' or image.width * image.height > 8_000_000
                            or max(image.size) > 8192):
                        raise ContractError('Evidence must be JPEG within image limits')
                    image.verify()
                with Image.open(BytesIO(data)) as image:
                    image.load()
        except (OSError, ValueError, binascii.Error, Image.DecompressionBombError,
                Image.DecompressionBombWarning) as error:
            raise ContractError('Evidence is not a complete valid JPEG within image limits') from error


def validate_observations(payload: dict, duration: float | None = None) -> dict:
    schema_check(payload, 'ml1-response.schema.json')
    if duration is not None:
        duration = video_duration(duration)
    ids = []
    for event in payload['events']:
        nonblank(event['id'])
        nonblank(event['description'])
        ids.append(event['id'].strip())
        start = seconds(event['start_sec'], duration=duration)
        end = seconds(event['end_sec'])
        if end < start or (duration is not None and end > duration):
            raise ContractError('Invalid observation interval')
        check_frames(event['evidence_frames'], duration)
    if len(ids) != len(set(ids)):
        raise ContractError('Observation IDs must be unique')
    return payload


def validate_rules(rules: list[dict]) -> dict[str, dict]:
    schema_check(dict(schema_version='1.0', rules=rules), 'rules-catalog.schema.json')
    catalog = {}
    for rule in rules:
        for field in ('id', 'title', 'document', 'section'):
            nonblank(rule[field])
        if rule['id'] != rule['id'].strip() or rule['id'] in catalog:
            raise ContractError('Rule IDs must be unique and have no surrounding spaces')
        if rule.get('is_demo') or rule['id'].startswith('demo:'):
            raise ContractError('Demo rules are not accepted in the live transport chain')
        for sign in rule['visual_signs']:
            nonblank(sign)
        try:
            url = urlsplit(rule['url'])
            valid = (url.scheme in {'http', 'https'} and url.hostname and url.port != 0
                     and not url.username and not url.password
                     and not any(c.isspace() or ord(c) < 32 for c in rule['url']))
        except ValueError:
            valid = False
        if not valid:
            raise ContractError('Invalid rule source URL')
        canonical = {name: rule[name].strip() for name in ('id','title','document','section','url')}
        canonical.update(visual_signs=[sign.strip() for sign in rule['visual_signs']], is_demo=False)
        catalog[rule['id']] = canonical
    if not catalog:
        raise ContractError('Rules catalog is empty; do not substitute a clean-video verdict')
    return catalog


def validate_matching_request(payload: dict) -> dict[str, dict]:
    schema_check(payload, 'ml2-request.schema.json')
    validate_observations(payload, video_duration(payload['duration_sec']))
    return validate_rules(payload['rules'])


def validate_result(payload: dict, duration: float | None = None,
                    rules: list[dict] | None = None) -> dict:
    schema_check(payload, 'analysis-result.schema.json')
    if duration is not None:
        duration = video_duration(duration)
    if (payload['verdict'] == 'violation') != bool(payload['violations']):
        raise ContractError('Verdict must agree with violations')
    catalog = validate_rules(rules) if rules is not None else None
    for event in payload['violations']:
        nonblank(event['type'])
        nonblank(event['description'])
        seconds(event['timecode_sec'], duration=duration)
        check_frames(event['evidence_frames'], duration)
        if catalog is not None:
            rule_id = event.get('rule_id')
            if rule_id not in catalog:
                raise ContractError('Event rule_id is not in the supplied catalog')
            if event.get('rule') is not None:
                supplied = validate_rules([event['rule']])
                if supplied.get(rule_id) != catalog[rule_id]:
                    raise ContractError('Event rule source differs from the supplied catalog')
    return payload


def validate_payload(payload: dict, *, kind: str = 'auto', duration: float | None = None,
                     rules: list[dict] | None = None, expect_empty: bool = False) -> dict:
    if not isinstance(payload, dict):
        raise ContractError('Expected a JSON object')
    if kind == 'auto':
        kind = 'job' if 'job_id' in payload else ('ml1' if 'schema_version' in payload else 'result')
    if kind == 'job':
        schema_check(payload, 'job-response.schema.json')
        if payload['status'] != 'done' or payload['stage'] != 'done':
            raise ContractError('Backend job is not done: ' + str(payload.get('error_code') or payload['status']))
        if payload.get('error') is not None or payload.get('error_code') is not None:
            raise ContractError('Completed backend job must not contain an error')
        duration = payload.get('duration_sec') if duration is None else duration
        validate_result(payload, duration, rules)
        events = payload['violations']
    elif kind == 'ml1':
        validate_observations(payload, duration)
        events = payload['events']
    elif kind == 'result':
        validate_result(payload, duration, rules)
        events = payload['violations']
    else:
        raise ContractError('Unknown JSON kind')
    if expect_empty and events:
        raise ContractError('Expected an empty event list')
    return dict(valid=True, kind=kind, event_count=len(events))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--kind', choices=['auto', 'ml1', 'result', 'job'], default='auto')
    parser.add_argument('--duration', type=float)
    parser.add_argument('--rules-path', type=Path)
    parser.add_argument('--expect-empty', action='store_true')
    args = parser.parse_args(argv)
    try:
        rules = read_json(args.rules_path)['rules'] if args.rules_path else None
        print(json.dumps(validate_payload(read_json(args.path), kind=args.kind,
            duration=args.duration, rules=rules, expect_empty=args.expect_empty)))
        return 0
    except (ValueError, OSError, KeyError) as error:
        print(json.dumps(dict(valid=False, error=str(error))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
