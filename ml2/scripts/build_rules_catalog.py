"""Build the public catalog from participant 2's git objects, without merging.

Paragraph checks are lexical evidence from a saved text, never a legal opinion
or validation that an ML detector can recognize the corresponding violation.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unicodedata
from urllib.parse import urlsplit

import jsonschema

REPO = Path(__file__).resolve().parents[2]
DEFAULT_REF = "origin/codex/ml1-local-analysis-handoff"
SOURCE_JSON = "ml1/outputs/forte_rules_kz.json"
SOURCE_TEXT = "ml1/work/legal/nbk-231-current.txt"
DOCUMENT = "Постановление Правления Национального Банка РК от 29.11.2019 № 231 (регистрация № 19680)"
EXPECTED_IDS = {f"KZ-CASH-{i:03d}" for i in range(1, 9)}


def nonblank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Source field must be a nonempty string: {field}")
    return value.strip()


def build_catalog(source: dict) -> dict:
    sources = {nonblank(s["id"], "source.id"): s for s in source["sources"]}
    rules = source["rules"]
    ids = [nonblank(r["id"], "id") for r in rules]
    if len(ids) != 8 or set(ids) != EXPECTED_IDS:
        raise ValueError("Expected exactly the eight distinct source KZ-CASH-001..008 rules")
    result = []
    for rule in rules:
        url = nonblank(sources[rule["source_id"]]["official_url"], "official_url")
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or any(c.isspace() for c in url)):
            raise ValueError("official_url must be an absolute HTTPS URL without credentials")
        signs = [nonblank(rule["visual_candidate"], "visual_candidate")]
        exclusions = rule.get("do_not_flag_if", [])
        if not isinstance(exclusions, list):
            raise ValueError("do_not_flag_if must be a list")
        signs += ["Не отмечать, если: " + nonblank(item, "do_not_flag_if") for item in exclusions]
        result.append(dict(id=rule["id"], title=nonblank(rule["type"], "type"),
            visual_signs=signs, document=DOCUMENT,
            section=nonblank(rule["paragraph"], "paragraph"), url=url, is_demo=False))
    catalog = dict(schema_version="1.0", rules=result)
    schema = json.loads((REPO / "contracts/rules-catalog.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(catalog)
    return catalog


def tokens(value: str) -> list[str]:
    value = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    return re.findall(r"[^\W\d_]+", value, re.UNICODE)


def shared_phrase(requirement: str, block: str) -> str | None:
    """Longest shared contiguous phrase, at least two words; no manual keywords."""
    words = tokens(requirement)
    text = " " + " ".join(tokens(block)) + " "
    for length in range(min(12, len(words)), 1, -1):
        candidates = {" ".join(words[i:i + length]) for i in range(len(words) - length + 1)}
        found = [p for p in candidates if " " + p + " " in text]
        if found:
            return min(found, key=lambda p: (-len(p), p))
    return None


def verify_paragraphs(source: dict, text: str) -> list[dict]:
    # Repeated paragraph numbers in appendices are checked independently.
    starts = list(re.finditer(r"(?m)^\s*(\d{1,3})\.\s+", text))
    blocks: dict[str, list[str]] = {}
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        blocks.setdefault(match[1], []).append(text[match.start():end])
    results = []
    for rule in source["rules"]:
        paragraph = nonblank(rule["paragraph"], "paragraph")
        requirement = nonblank(rule["legal_requirement"], "legal_requirement")
        numbers = list(dict.fromkeys(re.findall(r"\bп\.\s*(\d+)", paragraph)))
        checks = []
        for number in numbers:
            candidates = blocks.get(number, [])
            phrases = [p for b in candidates if (p := shared_phrase(requirement, b))]
            phrase = min(phrases, key=lambda p: (-len(p.split()), -len(p), p)) if phrases else None
            checks.append(dict(paragraph=int(number), number_found=bool(candidates),
                phrase=phrase, found=phrase is not None, number_occurrences=len(candidates)))
        results.append(dict(rule_id=rule["id"], section=paragraph, checks=checks,
                            found=bool(checks) and all(c["found"] for c in checks)))
    return results


def git_object(revision: str, path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{revision}:{path}"], cwd=REPO)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default=DEFAULT_REF)
    parser.add_argument("--output", type=Path, default=REPO / "data/rules.json")
    parser.add_argument("--report-json", type=Path)
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "rev-parse", "--verify", args.ref + "^{commit}"],
                                      cwd=REPO, text=True).strip()
    raw_json, raw_text = git_object(revision, SOURCE_JSON), git_object(revision, SOURCE_TEXT)
    source = json.loads(raw_json)
    catalog = build_catalog(source)
    checks = verify_paragraphs(source, raw_text.decode("utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = dict(checked_at=date.today().isoformat(), source_ref=args.ref,
        source_commit=revision, source_json_sha256=hashlib.sha256(raw_json).hexdigest(),
        source_text_sha256=hashlib.sha256(raw_text).hexdigest(), rule_count=len(catalog["rules"]),
        schema_valid=True, method="numbered paragraph plus longest shared normalized phrase of 2+ words",
        checks=checks)
    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # Missing text matches stay in the report; rules are never silently removed.


if __name__ == "__main__":
    main()
