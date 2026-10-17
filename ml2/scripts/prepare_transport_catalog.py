"""Structural conversion of the team's existing research catalog for HTTP tests.

This does not approve regulatory applicability or modify data/rules.json.
Unknown documents/clauses are rejected, never filled with invented values.
"""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def convert(source: dict) -> dict:
    sources = {row["id"]: row for row in source["sources"]}
    rules = []
    for row in source["rules"]:
        document = sources[row["source_id"]]
        required = [
            row.get("id"),
            row.get("type"),
            row.get("paragraph"),
            row.get("visual_candidate"),
            document.get("title"),
            document.get("official_url"),
        ]
        if not all(isinstance(value, str) and value.strip() for value in required):
            raise ValueError(
                "Research rule is missing a source or clause; cannot convert"
            )
        signs = [row["visual_candidate"]]
        signs += [
            "Required context: " + value for value in row.get("required_context", [])
        ]
        signs += ["Do not flag if: " + value for value in row.get("do_not_flag_if", [])]
        rules.append(
            dict(
                id=row["id"],
                title=row["type"],
                visual_signs=signs,
                document=document["title"],
                section=row["paragraph"],
                url=document["official_url"],
                is_demo=False,
            )
        )
    return dict(
        schema_version="1.0",
        rules=rules,
        integration_test_only=True,
        limitation="Structural conversion only; regulatory applicability and production catalog approval remain with participant 4",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=ROOT.parent / "ml1/outputs/forte_rules_kz.json"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "cache/integration/transport_catalog.json"
    )
    args = parser.parse_args()
    data = convert(json.loads(args.source.read_text(encoding="utf-8")))
    data["source_sha256"] = hashlib.sha256(args.source.read_bytes()).hexdigest()
    import jsonschema

    schema = json.loads(
        (ROOT.parent / "contracts/rules-catalog.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(data, schema)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"Converted {len(data['rules'])} existing rules for local transport test; source unchanged"
    )


if __name__ == "__main__":
    main()
