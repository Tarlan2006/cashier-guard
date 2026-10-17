"""Frozen local text inference only; no downloads, optimization or video reads."""

import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(
    HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1"
)
from backend.pipeline.perception.semantic_vocab import PROMPT_GROUPS


def main():
    import numpy as np
    import torch
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
        raise ValueError("Incomplete frozen text checkpoint")
    model.eval()
    tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
    tokenizer.enable_truncation(max_length=64)
    tokenizer.enable_padding(length=64, pad_id=1, pad_token="</s>")
    labels = [key for key, phrases in PROMPT_GROUPS.items() for _ in phrases]
    prompts = [text for phrases in PROMPT_GROUPS.values() for text in phrases]
    tokens = tokenizer.encode_batch(prompts)
    vectors = []
    with torch.no_grad():
        for offset in range(0, len(tokens), 4):
            ids = torch.tensor(
                [t.ids for t in tokens[offset : offset + 4]], dtype=torch.long
            )
            vectors.append(
                torch.nn.functional.normalize(
                    model(input_ids=ids).pooler_output, dim=-1
                ).numpy()
            )
    features = np.concatenate(vectors).astype(np.float32)
    with np.load(directory / "fixture_text_features.npz", allow_pickle=False) as old:
        phrases = old["prompts"].astype(str).tolist()
        error = max(
            float(np.max(np.abs(features[i] - old["features"][phrases.index(p)])))
            for i, p in enumerate(prompts)
            if p in phrases
        )
    if error > 1e-4:
        raise ValueError(f"Frozen text equivalence check failed: {error}")
    target = directory / "local_prompt_features.npz"
    np.savez_compressed(
        target,
        features=features,
        labels=np.asarray(labels),
        prompts=np.asarray(prompts),
    )
    (ROOT / "backend/pipeline/prompts/zone_states.txt").write_text(
        json.dumps(PROMPT_GROUPS, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = dict(
        model="google/siglip-base-patch16-224",
        revision="7fd15f0689c79d79e38b1c2e2e2370a7bf2761ed",
        license="Apache-2.0",
        trained=False,
        network=False,
        prompts=len(prompts),
        common_prompt_max_abs_error=error,
        sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
    )
    (ROOT / "cache/v5").mkdir(parents=True, exist_ok=True)
    (ROOT / "cache/v5/text_export.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report))


if __name__ == "__main__":
    main()
