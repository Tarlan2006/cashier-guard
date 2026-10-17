"""Write the local API response; never print/upload JPEG payloads."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.pipeline.analyze import analyze_report
from backend.pipeline.perception import load_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "cache/api/report.json")
    args = parser.parse_args()
    result = analyze_report(args.video, config=load_config(args.config))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "verdict",
                    "status",
                    "analysis_complete",
                    "elapsed_sec",
                    "enabled_rule_ids",
                    "warnings",
                )
            },
            ensure_ascii=False,
        )
    )
    print(f"Events: {len(result['events'])}; local response: {args.output}")


if __name__ == "__main__":
    main()
