"""Embed a fixed local anchor vocabulary using existing text weights only."""

import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

from backend.pipeline.perception.scene_vocab import SCENE_PROMPTS


def main():
    import torch
    import numpy as np
    from tokenizers import Tokenizer
    from transformers import SiglipTextModel

    torch.manual_seed(0)
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    directory = ROOT / "models/siglip-base-patch16-224"
    model, info = SiglipTextModel.from_pretrained(
        directory,
        local_files_only=True,
        attn_implementation="eager",
        output_loading_info=True,
    )
    if info.get("missing_keys") or info.get("mismatched_keys"):
        raise ValueError(
            f"Text checkpoint is incomplete: {info.get('missing_keys')}, {info.get('mismatched_keys')}"
        )
    model.eval()
    tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
    tokenizer.enable_truncation(max_length=64)
    tokenizer.enable_padding(length=64, pad_id=1, pad_token="</s>")
    labels, prompts = [], []
    for label, phrases in SCENE_PROMPTS.items():
        labels.extend([label] * len(phrases))
        prompts.extend(phrases)
    tokens = tokenizer.encode_batch(prompts)
    vectors = []
    with torch.no_grad():
        for offset in range(0, len(tokens), 4):
            ids = torch.tensor(
                [row.ids for row in tokens[offset : offset + 4]], dtype=torch.long
            )
            features = model(input_ids=ids).pooler_output
            vectors.append(torch.nn.functional.normalize(features, dim=-1).numpy())
    with np.load(
        directory / "fixture_text_features.npz", allow_pickle=False
    ) as original:
        logit_scale, logit_bias = original["logit_scale"], original["logit_bias"]
    target = directory / "scene_text_features.npz"
    features = np.concatenate(vectors).astype(np.float32)
    with np.load(
        directory / "fixture_text_features.npz", allow_pickle=False
    ) as original:
        original_prompts = original["prompts"].astype(str).tolist()
        common_errors = [
            float(
                np.max(
                    np.abs(
                        features[i]
                        - original["features"][original_prompts.index(prompt)]
                    )
                )
            )
            for i, prompt in enumerate(prompts)
            if prompt in original_prompts
        ]
    common_error = max(common_errors, default=0.0)
    if not common_errors or common_error > 1e-4:
        raise ValueError(
            f"Text-only load differs from the verified full-model export: {common_error}"
        )
    np.savez_compressed(
        target,
        features=features,
        labels=np.asarray(labels),
        prompts=np.asarray(prompts),
        logit_scale=logit_scale,
        logit_bias=logit_bias,
    )
    (ROOT / "backend/pipeline/prompts").mkdir(parents=True, exist_ok=True)
    (ROOT / "backend/pipeline/prompts/scene_anchors.txt").write_text(
        json.dumps(SCENE_PROMPTS, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = dict(
        source="google/siglip-base-patch16-224",
        revision="7fd15f0689c79d79e38b1c2e2e2370a7bf2761ed",
        license="Apache-2.0",
        no_training=True,
        no_network=True,
        text_missing_keys=sorted(info.get("missing_keys", [])),
        prompts=SCENE_PROMPTS,
        common_prompt_max_abs_error=common_error,
        sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
    )
    (ROOT / "cache/scene_text_export.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in report.items() if key != "prompts"}))


if __name__ == "__main__":
    main()
