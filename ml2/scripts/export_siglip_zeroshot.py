"""Export existing local SigLIP for fixture crop naming. No training/network.

Creates a fixed batch-1 224px ONNX image encoder plus small text vectors for
the explicit vocabulary in perception.fixtures. PyTorch and the text model
are required only in this offline export; the service imports neither.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["DO_NOT_TRACK"] = "1"

import cv2
import numpy as np
import torch
from tokenizers import Tokenizer
from transformers import AutoImageProcessor, SiglipModel

from backend.pipeline.perception.fixtures import MODEL_DIR, PROMPTS, preprocess_crop_bgr
from backend.pipeline.video import VideoReader

LOG = logging.getLogger(__name__)


class VisionWrapper(torch.nn.Module):
    def __init__(self, vision_model):
        super().__init__()
        self.vision_model = vision_model

    def forward(self, pixel_values):
        value = self.vision_model(
            pixel_values=pixel_values, return_dict=True
        ).pooler_output
        return value / value.norm(p=2, dim=-1, keepdim=True)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def peak_working_set_bytes():
    """OS-maintained high-water resident memory, without a dependency."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        process = ctypes.windll.kernel32.GetCurrentProcess
        process.restype = wintypes.HANDLE
        get_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not get_info(process(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError()
        return int(counters.PeakWorkingSetSize)
    import resource

    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * (
        1 if sys.platform == "darwin" else 1024
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=MODEL_DIR)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--validation-video", type=Path)
    parser.add_argument("--times", type=float, nargs="+", default=[0.0, 5.0, 10.0])
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT / "cache/siglip-zeroshot-export.json",
    )
    parser.add_argument("--reuse-export", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    if args.threads < 1:
        parser.error("threads must be positive")
    torch.manual_seed(0)
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    graph = args.model_dir / "vision_224.onnx"
    text_path = args.model_dir / "fixture_text_features.npz"
    source = json.loads(
        (PROJECT_ROOT / "cache/siglip-source.json").read_text(encoding="utf-8")
    )
    started = time.perf_counter()
    model = (
        SiglipModel.from_pretrained(
            args.model_dir, local_files_only=True, attn_implementation="eager"
        )
        .cpu()
        .eval()
    )
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "source_weights_sha256": sha256(args.model_dir / "model.safetensors"),
        "training": False,
        "network": False,
        "threads": args.threads,
        "reused_export": args.reuse_export,
        "load_sec": time.perf_counter() - started,
        "versions": {
            package: importlib.metadata.version(package)
            for package in (
                "torch",
                "transformers",
                "onnx",
                "onnxruntime",
                "tokenizers",
            )
        },
        "prompts": PROMPTS,
        "text_padding": "eos token id=1 to length 64",
        "text_tokenization": "pinned tokenizer.json including normalizer and EOS postprocessor",
        "input_shape": [1, 3, 224, 224],
        "opset": 17,
        "validation": [],
    }
    LOG.info("Loaded local SigLIP in %.2fs", report["load_sec"])
    tokenizer = Tokenizer.from_file(str(args.model_dir / "tokenizer.json"))
    tokenizer.enable_truncation(max_length=64)
    tokenizer.enable_padding(length=64, pad_id=1, pad_token="</s>")
    labels, prompts = [], []
    for label, texts in PROMPTS.items():
        labels.extend([label] * len(texts))
        prompts.extend(texts)
    encoded = tokenizer.encode_batch(prompts)
    vectors = []
    with torch.no_grad():
        for i in range(0, len(encoded), 4):
            ids = torch.tensor(
                [item.ids for item in encoded[i : i + 4]], dtype=torch.long
            )
            value = model.get_text_features(input_ids=ids).pooler_output
            vectors.append(torch.nn.functional.normalize(value, dim=-1).numpy())
    np.savez_compressed(
        text_path,
        features=np.concatenate(vectors).astype(np.float32),
        labels=np.asarray(labels),
        prompts=np.asarray(prompts),
        logit_scale=np.float32(model.logit_scale.exp().item()),
        logit_bias=np.float32(model.logit_bias.item()),
    )
    # Release the 116M-parameter text encoder before the ONNX exporter peaks.
    vision_model = model.vision_model
    del model, vectors
    gc.collect()
    wrapper = VisionWrapper(vision_model).eval()
    export_started = time.perf_counter()
    if not args.reuse_export:
        with torch.no_grad():
            torch.onnx.export(
                wrapper,
                (torch.zeros(1, 3, 224, 224),),
                str(graph),
                export_params=True,
                opset_version=17,
                do_constant_folding=True,
                input_names=["pixel_values"],
                output_names=["image_features"],
                dynamo=False,
            )
    elif not graph.is_file():
        parser.error(f"Missing graph: {graph}")
    report["export_sec"] = time.perf_counter() - export_started
    LOG.info(
        "%s %s in %.2fs",
        "Reused" if args.reuse_export else "Exported",
        graph.name,
        report["export_sec"],
    )
    processor = AutoImageProcessor.from_pretrained(
        args.model_dir, local_files_only=True, backend="pil"
    )
    frames = []
    if args.validation_video:
        with VideoReader(args.validation_video) as reader:
            for timestamp in args.times:
                sample = reader.read_at(timestamp)
                height, width = sample.frame_bgr.shape[:2]
                crop = sample.frame_bgr[
                    height // 4 : 3 * height // 4, width // 4 : 3 * width // 4
                ]
                frames.append((sample.actual_timestamp_sec, crop))
    else:
        rng = np.random.default_rng(0)
        frames = [(0.0, rng.integers(0, 256, (127, 193, 3), np.uint8))]
    validation = []
    with torch.no_grad():
        for timestamp, frame in frames:
            expected_input = processor(
                images=[cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)], return_tensors="pt"
            )["pixel_values"]
            actual_input = preprocess_crop_bgr(frame)
            expected_feature = wrapper(expected_input).numpy()
            validation.append((timestamp, actual_input, expected_feature))
            input_error = np.abs(actual_input - expected_input.numpy())
            report["validation"].append(
                {
                    "actual_timestamp_sec": timestamp,
                    "preprocessing_max_abs_error": float(input_error.max()),
                    "preprocessing_allclose": bool(
                        np.allclose(
                            actual_input, expected_input.numpy(), rtol=0, atol=1e-7
                        )
                    ),
                }
            )
    del wrapper, vision_model, processor
    gc.collect()
    import onnx
    import onnxruntime as ort

    onnx.checker.check_model(str(graph))
    gc.collect()
    options = ort.SessionOptions()
    options.intra_op_num_threads, options.inter_op_num_threads = args.threads, 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    session = ort.InferenceSession(
        str(graph), sess_options=options, providers=["CPUExecutionProvider"]
    )
    for record, (_, values, expected) in zip(report["validation"], validation):
        session.run(["image_features"], {"pixel_values": values})
        infer_started = time.perf_counter()
        actual = session.run(["image_features"], {"pixel_values": values})[0]
        record.update(
            {
                "onnx_warm_sec": time.perf_counter() - infer_started,
                "feature_max_abs_error": float(np.abs(actual - expected).max()),
                "feature_allclose": bool(
                    np.allclose(actual, expected, rtol=1e-3, atol=1e-4)
                ),
            }
        )
    report.update(
        {
            "onnx_sha256": sha256(graph),
            "text_features_sha256": sha256(text_path),
            "onnx_size_bytes": graph.stat().st_size,
            "peak_working_set_bytes": peak_working_set_bytes(),
            "passed": all(
                row["preprocessing_allclose"] and row["feature_allclose"]
                for row in report["validation"]
            ),
            "total_sec": time.perf_counter() - started,
        }
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "passed",
                    "load_sec",
                    "export_sec",
                    "total_sec",
                    "validation",
                )
            },
            indent=2,
        )
    )
    if not report["passed"]:
        raise SystemExit("Export equivalence checks failed")


if __name__ == "__main__":
    main()
