"""Export the frozen local RT-DETR checkpoint and verify raw output equivalence.

No training, weight download or network calls. The ONNX graph has one fixed
NCHW input (batch=1); configure the runtime with the exported image size.

Example from the repository root::

    .venv/Scripts/python scripts/export_perception_onnx.py \
        --validation-video data/open/videos/X-1.mov --times 0 5 10
"""

from __future__ import annotations

import argparse
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
from transformers import AutoImageProcessor, RTDetrConfig, RTDetrForObjectDetection

from backend.pipeline.video import VideoReader
from backend.pipeline.perception.detector import preprocess_bgr

LOG = logging.getLogger(__name__)


class ExportWrapper(torch.nn.Module):
    """Keep only the two raw outputs consumed by local postprocessing."""

    def __init__(self, model: RTDetrForObjectDetection) -> None:
        super().__init__()
        self.model = model

    def forward(self, pixel_values: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        output = self.model(pixel_values=pixel_values, return_dict=True)
        return output.logits, output.pred_boxes


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-dir", type=Path, default=PROJECT_ROOT / "models/rtdetr_r18vd"
    )
    parser.add_argument("--size", type=int, default=384)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validation-video", type=Path, required=True)
    parser.add_argument("--times", type=float, nargs="+", default=[0.0, 5.0, 10.0])
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT / "cache/perception-onnx-export-384.json",
    )
    parser.add_argument(
        "--reuse-export",
        action="store_true",
        help="Validate an already exported local graph",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    if args.size < 256 or args.size % 32 or args.threads < 1:
        parser.error(
            "size must be a multiple of 32 and at least 256; threads must be positive"
        )
    if not args.validation_video.is_file():
        parser.error(f"Validation video does not exist: {args.validation_video}")
    output_path = args.output or args.model_dir / f"model_{args.size}.onnx"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(0)
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    import onnx
    import onnxruntime as ort

    source_path = PROJECT_ROOT / "cache/rtdetr-source.json"
    source = (
        json.loads(source_path.read_text(encoding="utf-8"))
        if source_path.is_file()
        else {
            "id": "PekingU/rtdetr_r18vd",
            "revision": "ac77a11ff0170a41b771c03264987f8ce2b0d753",
            "license": "Apache-2.0",
        }
    )
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "source_weights_sha256": sha256(args.model_dir / "model.safetensors"),
        "source_config_sha256": sha256(args.model_dir / "config.json"),
        "versions": {
            package: importlib.metadata.version(package)
            for package in ("torch", "transformers", "onnx", "onnxruntime", "numpy")
        },
        "training": False,
        "network": False,
        "input": {
            "name": "pixel_values",
            "shape": [1, 3, args.size, args.size],
            "dtype": "float32",
        },
        "outputs": ["logits", "pred_boxes"],
        "opset_version": 17,
        "threads": args.threads,
        "equivalence_tolerance": {"rtol": 1e-3, "atol": 1e-3},
        "validation_video": args.validation_video.name,
        "validation_frames": [],
    }
    started = time.perf_counter()
    config = RTDetrConfig.from_pretrained(args.model_dir, local_files_only=True)
    config.disable_custom_kernels = True
    config.anchor_image_size = None
    config.return_dict = True
    model = (
        RTDetrForObjectDetection.from_pretrained(
            args.model_dir, config=config, local_files_only=True
        )
        .cpu()
        .eval()
    )
    wrapper = ExportWrapper(model).eval()
    processor = AutoImageProcessor.from_pretrained(
        args.model_dir, local_files_only=True, backend="pil"
    )
    report["torch_load_sec"] = time.perf_counter() - started
    LOG.info("Loaded frozen local model in %.3fs", report["torch_load_sec"])
    export_started = time.perf_counter()
    if not args.reuse_export:
        try:
            with torch.no_grad():
                torch.onnx.export(
                    wrapper,
                    (torch.zeros(1, 3, args.size, args.size, dtype=torch.float32),),
                    str(output_path),
                    export_params=True,
                    opset_version=17,
                    do_constant_folding=True,
                    input_names=["pixel_values"],
                    output_names=["logits", "pred_boxes"],
                    dynamo=False,
                )
        except Exception as error:
            report.update(
                status="export_failed",
                error=repr(error),
                export_sec=time.perf_counter() - export_started,
            )
            write_json(args.report, report)
            LOG.exception("ONNX export failed")
            raise
    elif not output_path.is_file():
        parser.error(f"Cannot reuse missing ONNX graph: {output_path}")
    report["export_sec"] = time.perf_counter() - export_started
    LOG.info("Exported %s in %.3fs", output_path.name, report["export_sec"])
    onnx.checker.check_model(str(output_path))
    report["onnx_sha256"] = sha256(output_path)
    options = ort.SessionOptions()
    options.intra_op_num_threads = args.threads
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    session_started = time.perf_counter()
    session = ort.InferenceSession(
        str(output_path), sess_options=options, providers=["CPUExecutionProvider"]
    )
    report["ort_load_sec"] = time.perf_counter() - session_started
    LOG.info("Loaded CPU ONNX session in %.3fs", report["ort_load_sec"])
    passed = True
    with VideoReader(args.validation_video) as reader:
        for timestamp in args.times:
            sample = reader.read_at(timestamp)
            rgb = cv2.cvtColor(sample.frame_bgr, cv2.COLOR_BGR2RGB)
            pixel_values = processor(
                images=[rgb],
                return_tensors="pt",
                size={"height": args.size, "width": args.size},
            )["pixel_values"].contiguous()
            local_pixel_values = preprocess_bgr(sample.frame_bgr, args.size)
            local_pixel_values = np.asarray(local_pixel_values, dtype=np.float32)
            if local_pixel_values.ndim == 3:
                local_pixel_values = local_pixel_values[None]
            reference_pixel_values = pixel_values.numpy()
            preprocessing_error = np.abs(local_pixel_values - reference_pixel_values)
            preprocessing_equivalent = bool(
                np.allclose(
                    local_pixel_values, reference_pixel_values, rtol=0.0, atol=1e-7
                )
            )
            passed = passed and preprocessing_equivalent
            with torch.no_grad():
                # One warmup precedes the measured pass on each real frame.
                wrapper(pixel_values)
                torch_started = time.perf_counter()
                expected = [tensor.numpy() for tensor in wrapper(pixel_values)]
                torch_sec = time.perf_counter() - torch_started
            inputs = {"pixel_values": pixel_values.numpy()}
            session.run(None, inputs)
            ort_started = time.perf_counter()
            actual = session.run(None, inputs)
            ort_sec = time.perf_counter() - ort_started
            frame_result = {
                "requested_timestamp_sec": timestamp,
                "actual_timestamp_sec": sample.actual_timestamp_sec,
                "torch_warm_sec": torch_sec,
                "onnx_warm_sec": ort_sec,
                "preprocessing": {
                    "allclose_atol_1e-7_rtol_0": preprocessing_equivalent,
                    "max_abs_error": float(preprocessing_error.max()),
                    "mean_abs_error": float(preprocessing_error.mean()),
                },
                "outputs": {},
            }
            for name, torch_value, ort_value in zip(
                report["outputs"], expected, actual
            ):
                difference = np.abs(torch_value - ort_value)
                equivalent = bool(
                    np.allclose(torch_value, ort_value, rtol=1e-3, atol=1e-3)
                )
                passed = passed and equivalent
                frame_result["outputs"][name] = {
                    "shape": list(ort_value.shape),
                    "allclose": equivalent,
                    "max_abs_error": float(difference.max()),
                    "mean_abs_error": float(difference.mean()),
                }
            report["validation_frames"].append(frame_result)
            LOG.info(
                "Frame %.3fs: PyTorch %.3fs, ONNX %.3fs, raw equivalent=%s",
                sample.actual_timestamp_sec,
                torch_sec,
                ort_sec,
                all(item["allclose"] for item in frame_result["outputs"].values()),
            )
    report["warm_forward_summary_sec"] = {}
    for backend in ("torch", "onnx"):
        durations = np.asarray(
            [item[f"{backend}_warm_sec"] for item in report["validation_frames"]]
        )
        report["warm_forward_summary_sec"][backend] = {
            "count": int(durations.size),
            "mean": float(durations.mean()),
            "p50": float(np.percentile(durations, 50)),
            "p90": float(np.percentile(durations, 90)),
            "max": float(durations.max()),
        }
    report.update(
        status="passed" if passed else "equivalence_failed",
        total_sec=time.perf_counter() - started,
    )
    write_json(args.report, report)
    metadata = dict(report)
    metadata["validation_report"] = (
        str(args.report.relative_to(PROJECT_ROOT))
        if args.report.is_relative_to(PROJECT_ROOT)
        else str(args.report)
    )
    write_json(output_path.with_suffix(".json"), metadata)
    print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    if not passed:
        raise SystemExit(
            "Raw ONNX outputs exceeded equivalence tolerance; do not use this graph"
        )


if __name__ == "__main__":
    main()
