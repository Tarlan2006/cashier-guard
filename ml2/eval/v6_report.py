"""Build a reviewable aggregate report without committing input labels/crops."""

from datetime import datetime
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def main():
    tracks = json.loads((ROOT / "cache/v6/tracks.json").read_text(encoding="utf-8"))
    zones = json.loads(
        (ROOT / "cache/v6/zones/results.json").read_text(encoding="utf-8")
    )
    timing = json.loads(
        (ROOT / "cache/v6/long_benchmark.json").read_text(encoding="utf-8")
    )
    lines = [
        "# v6: video-level rule validation and weakly supervised zones",
        "",
        f"Date: {datetime.now().isoformat(timespec='seconds')}; seed=42; CPU; Python 3.12.",
        "",
        "40 unique MD5 groups: 21 violation-labelled and 19 normal. 4/47 and 5/48 are each one group. "
        "The two reference times of 4/47 are retained. Input facts are the existing v5 production facts; "
        "all 40 were reevaluated by the new track rules without image inference or labels in runtime code. "
        "The long-video timing is a separate fresh, uncached full perception run.",
        "",
        "## A1/A2: independent video-level and timestamp metrics",
        "",
        "Gate: TP >= 3 and FP <= 1 on normal videos. Reference-time error is descriptive only. "
        "For each detected positive video it is the minimum absolute distance between any emitted onset "
        "and any reference time; MAE averages those per-video minima. Missed videos are excluded from MAE "
        "and remain FN. This optimistic nearest-event statistic does not establish correct event type. "
        "The gate is an in-sample development screen, not an independent generalization estimate.",
        "",
        "| Rule | TP /21 | FP /19 | FN | TN | Onset MAE, s | Enabled | Source |",
        "|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in tracks["metrics"]:
        error = (
            "—"
            if row["timestamp_mae_sec"] is None
            else f"{row['timestamp_mae_sec']:.2f}"
        )
        lines.append(
            f"| {row['rule_id']} | {row['TP']} | {row['FP']} | {row['FN']} | {row['TN']} | {error} | no | {'v5 reference only' if 'source' in row else 'v6 tracks only'} |"
        )
    lines += [
        "",
        "Global settings: track presence hold=3 s, departure/return confirmation=2 s; initial workplace from "
        "the first 3 s of cashier observations; radius=0.5 torso short side, clamped to 0.035–0.15 image diagonals; "
        "departure boundary=1.15 radius; reidentification is unchanged. Reflections and uncertain tracks are excluded. "
        "Detection gaps over 1 s never prove continuous presence. Once a track is confirmed, onset is backdated "
        "to its actual observations, never to the confirmation time. No thresholds were selected per video.",
        "",
        "The four zero-shot state rows are retained solely as the previously computed v5 baseline; they are "
        "not a v6 linear-classifier evaluation and cannot be enabled by this report. The overlap rule's TP=2 "
        "includes video 1, whose annotated issue is a different action: binary TP is not rule-type correctness.",
        "",
        "### All 40 unique videos",
        "",
        "Cell values are emitted onset times in seconds; — means no candidate.",
        "",
        "| Video aliases | Label | Away with client | Left | Returned | >=3 people at table | >=2 clients |",
        "|---|---|---|---|---|---|---|",
    ]
    rules = [
        "cashier_away_with_client",
        "cashier_left_workplace",
        "cashier_returned_workplace",
        "three_people_at_table",
        "two_clients_three_seconds",
    ]
    for row in tracks["rows"]:
        cells = [
            ", ".join(
                f"{e['timecode_sec']:.1f}"
                for e in row["events"]
                if e["rule_id"] == rule
            )
            or "—"
            for rule in rules
        ]
        lines.append(
            "| "
            + " | ".join(
                [
                    "/".join(map(str, row["aliases"])),
                    "violation" if row["positive"] else "normal",
                ]
                + cells
            )
            + " |"
        )
    lines += [
        "",
        "## A3: logistic regression on frozen SigLIP zone crops",
        "",
        "One fixed configuration: StandardScaler + LogisticRegression(C=0.1, class_weight=balanced, "
        "max_iter=2000, random_state=42). Scaling and classifier fit exclusively on training MD5 groups; "
        "leave-one-video-out; no hyperparameter search. Frozen SigLIP was not fine-tuned. "
        "Before frames at -2/-1 s were extracted but explicitly left unlabeled: the PDF does not establish "
        "their state. After samples use 0/+0.5/+1 s. Paired controls use the same reference seconds, "
        "clamped to the clip's last available frame; no hand-adjusted offsets. "
        "Normal video 16 is excluded as an empty-table label because its description explicitly concerns a bag "
        "being received. Other cleanup controls remain weak episode labels, not verified frame annotations. "
        "The 4/47 duplicate is used once. There is no defensible frame-state ground truth in this source.",
        "",
        "| Zone | Unique videos | Labelled frames | LOVO evaluated | Accuracy vs weak labels | Majority baseline | Normal videos with positive output |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for z in zones:
        accuracy = "not evaluable" if z["accuracy"] is None else f"{z['accuracy']:.1%}"
        false = (
            "not evaluable"
            if not z["evaluated_normal_videos"]
            else f"{len(z['false_normal_videos'])}/{z['evaluated_normal_videos']} ({', '.join(map(str,z['false_normal_videos']))})"
        )
        lines.append(
            f"| {z['domain']} | {z['unique_videos']} | {z['labeled_frames']} | {z['evaluated_frames']} | {accuracy} | {z['majority_baseline']:.1%} | {false} |"
        )
    lines += [
        "",
        "Table classification is worse than the majority baseline and provides no useful evidence. "
        "A positive object state on a normal video is not by itself a violation; the last column is the requested "
        "normal-video alarm proxy, not a validated downstream FP count. Safe has only one open and one closed "
        "video; each held-out fold has a single training class, so accuracy/FP are unavailable, not zero. "
        "Both experimental numeric heads were fitted for reproducibility and kept only in ignored cache. "
        "The runtime adapter supports numeric linear heads and has no zero-shot fallback; no state rule is enabled.",
        "",
        "## A4/A5: publication and fresh long-video timing",
        "",
        "No rule passes the gate. configs/rule_validation.json records the measurements and an empty whitelist. "
        "analyze_video emits no rule events; analyze_report explicitly returns partial and a null verdict when "
        "coverage is insufficient. A processing failure in the list-only API raises AnalysisIncomplete instead "
        "of returning an empty list. HTTP packaging must preserve errors as non-2xx responses.",
        "",
        "| Input | Duration, s | Full wall time, s | Under 170 s | Sampling changes | Cache |",
        "|---|---:|---:|---|---|---|",
    ]
    lines.append(
        f"| Open 14 + same clip, video-only reencode | {timing['input_duration_sec']:.2f} | {timing['wall_elapsed_sec']:.2f} | {'yes' if timing['wall_elapsed_sec'] < 170 else 'no'} | {timing.get('sampling', {}).get('interval_changes', timing.get('sampling', {}).get('changes', []))} | no |"
    )
    lines += [
        "",
        "The source's measured duration differs from the rounded 145 s in the task; the concatenation is ~285 s. "
        "This run finishes before the 150 s adaptation threshold, so no step increase is necessary. "
        "The configured schedule is 0.5 s before 150 wall seconds, then 2–10 s adaptively; soft stop=168 s, "
        "outer deadline=170 s (1 s cleanup reserve). Existing fake-clock and real hung-worker tests exercise "
        "adaptation and forced termination. This single latency measurement is not a worst-case guarantee.",
        "",
        "## Weak points / next actions",
        "",
        "- Pure departures also occur in normal scenes; tracks cannot identify cash/documents left on a desk.",
        "- Two-client overlap also fires on normal 19 and detects only two positive-labelled videos, one with a different issue.",
        "- Role/anchor errors remain: cashier unknown in 5/48; machine missing in 45; safe missing in 26 and false in 44.",
        "- No operational door detector or verified table segmentation; workstation origin and height are geometric proxies.",
        "- Accurate before/after state labels and independent held-out scene groups are required before training can be assessed.",
        "- No closed-test frames, VLM, cloud AI, per-video runtime exceptions or private media/labels were committed.",
        "",
        "Reproduce: python eval/v6_tracks.py; python eval/v6_zones.py; python eval/v6_long_video.py; "
        "python -m unittest discover -s tests; python eval/v6_report.py. Evaluation requires the ignored open data, "
        "manual labels, v5 facts and local model weights.",
        "",
    ]
    # Detailed per-video labels/timecodes are local artifacts, never a Git report.
    out = ROOT / "cache/v6/report.private.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
