"""Weak manual state labels, frozen crop features, MD5-safe leave-video-out.

The PDF describes episodes, not frame state annotations. Before-event states
are deliberately unlabeled. Reported scores are weak-label agreement only.
"""

import json
from pathlib import Path
import sys
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, balanced_accuracy_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.pipeline.video import VideoReader
from backend.pipeline.perception.scene_geometry import desk_box
from backend.pipeline.perception.anchors_v2 import crop_box
from backend.pipeline.perception.fixtures import get_fixture_classifier


def main():
    manifest = json.loads(
        (ROOT / "cache/all40/stage1/manifest.json").read_text(encoding="utf-8")
    )
    by_num = {n: item for item in manifest for n in item["nums"]}
    labels = {
        r["video_num"]: r
        for r in json.loads(
            (ROOT / "eval/manual_labels.json").read_text(encoding="utf-8")
        )["videos"]
    }
    # Only descriptions explicitly mentioning objects left/removed or a safe
    # remaining open/being closed supply state labels. No per-video crop zones.
    table_positive = [
        r
        for r in labels.values()
        if r["type"]
        in {
            "Неубранная наличность",
            "Сумка без присмотра",
            "Оставленные документы и штампы",
            "Наличные без присмотра",
        }
    ]
    cases = []
    excluded_labels = []
    seen = set()
    for row in table_positive:
        item = by_num[row["video_num"]]
        if item["md5"] in seen:
            continue
        seen.add(item["md5"])
        cases.append(("table", item, row["time_sec"], 1, "manual_episode_after"))
        for normal in row["paired_normal_videos"]:
            control = by_num[normal]
            if control["md5"] in seen:
                continue
            description = labels[normal]["description"].lower()
            # A clean overall video is not an empty-table label. The green-bag
            # control, for example, explicitly describes an object being held.
            if not (
                "очищ" in description
                or (
                    "шкаф" in description
                    and any(
                        word in description for word in ("убира", "помещ", "кладёт")
                    )
                )
            ):
                excluded_labels.append(
                    dict(
                        video=normal,
                        reason="normal_episode_does_not_describe_table_cleanup",
                    )
                )
                continue
            seen.add(control["md5"])
            cases.append(
                (
                    "table",
                    control,
                    row["time_sec"],
                    0,
                    "paired_control_same_reference_weak",
                )
            )
    for row in labels.values():
        if row["type"] == "Открытый сейф":
            cases.append(
                (
                    "safe",
                    by_num[row["video_num"]],
                    row["time_sec"],
                    1,
                    "manual_episode_after",
                )
            )
            cases.extend(
                (
                    "safe",
                    by_num[n],
                    row["time_sec"],
                    0,
                    "paired_control_same_reference_weak",
                )
                for n in row["paired_normal_videos"]
            )
    output = ROOT / "cache/v6/zones"
    output.mkdir(parents=True, exist_ok=True)
    encoder = get_fixture_classifier(
        str(ROOT / "models/siglip-base-patch16-224"), 2, "cpu"
    )
    rows, features, missing = [], [], []
    for domain, item, t, label, source in cases:
        facts = json.loads(
            (
                ROOT / f"cache/v5/production_inputs/{item['num']:02}.facts.json"
            ).read_text(encoding="utf-8")
        )
        box = (
            desk_box(facts)
            if domain == "table"
            else next(
                (o["bbox"] for o in facts.get("fixtures", []) if o["class"] == "safe"),
                None,
            )
        )
        if box is None:
            missing.append(
                dict(video=item["num"], domain=domain, reason="anchor_missing")
            )
            continue
        with VideoReader(item["path"]) as reader:
            for offset in (-2.0, -1.0, 0.0, 0.5, 1.0):
                sample = reader.read_at(
                    min(max(0.0, t + offset), reader.metadata.duration_sec - 0.15)
                )
                crop = crop_box(sample.frame_bgr, box)
                feature = encoder.encode_crop(crop)
                features.append(feature)
                rows.append(
                    dict(
                        video=item["num"],
                        md5=item["md5"],
                        domain=domain,
                        reference_sec=t,
                        actual_sec=sample.actual_timestamp_sec,
                        phase="before" if offset < 0 else "after",
                        label=None if offset < 0 else label,
                        source=source,
                        normal_video=labels[item["num"]]["level"] == "none",
                    )
                )
        print(f"features {domain} video={item['num']}", flush=True)
    x = np.stack(features)
    reports = []
    for domain in ("table", "safe"):
        indices = np.array(
            [
                i
                for i, r in enumerate(rows)
                if r["domain"] == domain and r["label"] is not None
            ]
        )
        y = np.array([rows[i]["label"] for i in indices], dtype=int)
        groups = np.array([rows[i]["md5"] for i in indices])
        predictions = np.full(len(indices), -1, dtype=int)
        folds = []
        for group in sorted(set(groups)):
            train, test = groups != group, groups == group
            if len(set(y[train])) < 2:
                folds.append(
                    dict(
                        video=rows[indices[np.flatnonzero(test)[0]]]["video"],
                        evaluable=False,
                        reason="single_class_training_fold",
                    )
                )
                continue
            model = make_pipeline(
                StandardScaler(),
                LogisticRegression(
                    C=0.1, class_weight="balanced", max_iter=2000, random_state=42
                ),
            )
            model.fit(x[indices[train]], y[train])
            predictions[test] = model.predict(x[indices[test]])
            folds.append(
                dict(
                    video=rows[indices[np.flatnonzero(test)[0]]]["video"],
                    evaluable=True,
                    truth=int(y[test][0]),
                    predicted=list(map(int, predictions[test])),
                    accuracy=float(accuracy_score(y[test], predictions[test])),
                )
            )
        valid = predictions >= 0
        normal = np.array([rows[i]["normal_video"] for i in indices])
        false_videos = sorted(
            {
                rows[indices[i]]["video"]
                for i in range(len(indices))
                if valid[i] and normal[i] and predictions[i] == 1
            }
        )
        report = dict(
            domain=domain,
            unique_videos=len(set(groups)),
            labeled_frames=len(indices),
            evaluated_frames=int(valid.sum()),
            accuracy=(
                float(accuracy_score(y[valid], predictions[valid]))
                if valid.any()
                else None
            ),
            balanced_accuracy=(
                float(balanced_accuracy_score(y[valid], predictions[valid]))
                if valid.any()
                else None
            ),
            majority_baseline=float(max(np.mean(y == 0), np.mean(y == 1))),
            false_normal_videos=false_videos,
            evaluated_normal_videos=len(
                {
                    rows[indices[i]]["video"]
                    for i in range(len(indices))
                    if normal[i] and valid[i]
                }
            ),
            folds=folds,
            label_quality="weak_episode_labels; no verified before-frame state labels",
        )
        reports.append(report)
        if len(set(y)) == 2:
            model = make_pipeline(
                StandardScaler(),
                LogisticRegression(
                    C=0.1, class_weight="balanced", max_iter=2000, random_state=42
                ),
            )
            model.fit(x[indices], y)
            # Numeric arrays only, no executable pickle. Not enabled in runtime.
            np.savez_compressed(
                output / f"{domain}_linear.npz",
                mean=model[0].mean_,
                scale=model[0].scale_,
                coef=model[1].coef_,
                intercept=model[1].intercept_,
                classes=model[1].classes_,
            )
    np.savez_compressed(output / "features.npz", features=x)
    (output / "samples.json").write_text(
        json.dumps(
            dict(rows=rows, missing=missing, excluded_labels=excluded_labels),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (output / "results.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
