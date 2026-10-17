"""All 40 MD5 groups, video-level gate and separate onset error."""

import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.pipeline.track_rules import evaluate_track_rules, TRACK_RULE_IDS


def main():
    manifest = json.loads(
        (ROOT / "cache/all40/stage1/manifest.json").read_text(encoding="utf-8")
    )
    labels = {
        r["video_num"]: r
        for r in json.loads(
            (ROOT / "eval/manual_labels.json").read_text(encoding="utf-8")
        )["videos"]
    }
    rows = []
    for item in manifest:
        facts = json.loads(
            (
                ROOT / f"cache/v5/production_inputs/{item['num']:02}.facts.json"
            ).read_text(encoding="utf-8")
        )
        events = evaluate_track_rules(facts)
        rows.append(
            dict(
                video=item["num"],
                aliases=item["nums"],
                positive=labels[item["num"]]["level"] != "none",
                reference_times=item["event_times"],
                events=events,
            )
        )
    metrics = []
    for rule in sorted(TRACK_RULE_IDS):
        selected = [[e for e in row["events"] if e["rule_id"] == rule] for row in rows]
        tp = sum(
            bool(events) and row["positive"] for row, events in zip(rows, selected)
        )
        fp = sum(
            bool(events) and not row["positive"] for row, events in zip(rows, selected)
        )
        errors = [
            min(
                abs(e["timecode_sec"] - t)
                for e in events
                for t in row["reference_times"]
            )
            for row, events in zip(rows, selected)
            if row["positive"] and events and row["reference_times"]
        ]
        metrics.append(
            dict(
                rule_id=rule,
                TP=tp,
                FP=fp,
                FN=21 - tp,
                TN=19 - fp,
                timestamp_mae_sec=float(np.mean(errors)) if errors else None,
                timestamp_errors_sec=errors,
                enabled=tp >= 3 and fp <= 1,
            )
        )
    for rule in (
        "items_after_cashier_left",
        "previous_items_with_new_client",
        "safe_open_while_working",
        "unlocked_laptop_after_cashier_left",
    ):
        tp = fp = 0
        errors = []
        for row in rows:
            previous = json.loads(
                (
                    ROOT / f"cache/v5/final_roles_states/{row['video']:02}.facts.json"
                ).read_text(encoding="utf-8")
            )
            events = [
                e for e in previous["semantic_engine"]["events"] if e["rule_id"] == rule
            ]
            row.setdefault("previous_zero_shot_events", []).extend(events)
            if events:
                if row["positive"]:
                    tp += 1
                    errors.append(
                        min(
                            abs(e["timecode_sec"] - t)
                            for e in events
                            for t in row["reference_times"]
                        )
                    )
                else:
                    fp += 1
        metrics.append(
            dict(
                rule_id=rule,
                TP=tp,
                FP=fp,
                FN=21 - tp,
                TN=19 - fp,
                timestamp_mae_sec=float(np.mean(errors)) if errors else None,
                enabled=False,
                source="v5 zero-shot reference; replaced and disabled",
            )
        )
    output = ROOT / "cache/v6"
    output.mkdir(parents=True, exist_ok=True)
    (output / "tracks.json").write_text(
        json.dumps(dict(rows=rows, metrics=metrics), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (ROOT / "configs/rule_validation.json").write_text(
        json.dumps(
            dict(
                version="v6",
                video_count=40,
                positive_count=21,
                normal_count=19,
                criterion=dict(min_TP=3, max_FP=1),
                enabled_rule_ids=[r["rule_id"] for r in metrics if r["enabled"]],
                metrics=[
                    {key: value for key, value in row.items() if key != "timestamp_errors_sec"}
                    for row in metrics
                ],
            ),
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
