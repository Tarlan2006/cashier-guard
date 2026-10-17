"""Explicit one-time model setup; never imported by the service.

Copy a verified exported bundle, or download pinned upstream checkpoints and
export them locally. Every downloaded source file is checked against SHA-256.
Local ONNX exports additionally run numerical parity checks; their hashes are
recorded because exporter/platform metadata can change the binary graph hash.
"""

from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "configs/model_manifest.json"
DEPTH_MANIFEST = ROOT / "configs/depth_model_manifest.json"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_files(directory: Path, files: dict) -> None:
    directory = directory.resolve()
    for name, expected in files.items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory):
            raise ValueError("Manifest path escapes the model directory")
        if (
            not path.is_file()
            or path.stat().st_size != expected["size"]
            or digest(path) != expected["sha256"]
        ):
            raise ValueError(f"Missing/corrupt model asset: {name}")


def download_sources(directory: Path, manifest: dict):
    for model in manifest["models"]:
        prefix = model["directory"] + "/"
        for relative, expected in manifest["source_files"].items():
            if not relative.startswith(prefix):
                continue
            path = directory / relative
            if (
                path.exists()
                and path.stat().st_size == expected["size"]
                and digest(path) == expected["sha256"]
            ):
                continue
            name = relative[len(prefix) :]
            url = f"https://huggingface.co/{model['name']}/resolve/{model['revision']}/{name}"
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".part")
            try:
                with urllib.request.urlopen(
                    url, timeout=60
                ) as response, temporary.open("wb") as stream:
                    shutil.copyfileobj(response, stream)
                if (
                    temporary.stat().st_size != expected["size"]
                    or digest(temporary) != expected["sha256"]
                ):
                    raise ValueError(f"Downloaded source hash mismatch: {relative}")
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
    verify_files(directory, manifest["source_files"])
    for model in manifest["models"]:
        card = (
            (directory / model["directory"] / "README.md")
            .read_text(encoding="utf-8")
            .lower()
        )
        if "license: apache-2.0" not in card:
            raise ValueError("Pinned source card does not declare Apache-2.0")


def export_local(directory: Path):
    # Prompt-export helpers deliberately use a repository-relative models path.
    if directory.resolve() != (ROOT / "models").resolve():
        raise ValueError(
            "Download/export mode requires the default ml2/models directory; --source supports any output"
        )
    import cv2
    import numpy as np

    cache = ROOT / "cache/model_setup"
    cache.mkdir(parents=True, exist_ok=True)
    video = cache / "synthetic_validation.mov"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10, (128, 96))
    if not writer.isOpened():
        raise RuntimeError("Cannot create synthetic export-validation video")
    rng = np.random.default_rng(42)
    try:
        for _ in range(30):
            writer.write(rng.integers(0, 256, (96, 128, 3), dtype=np.uint8))
    finally:
        writer.release()
    commands = [
        [
            "export_perception_onnx.py",
            "--model-dir",
            str(directory / "rtdetr_r18vd"),
            "--validation-video",
            str(video),
            "--times",
            "0",
            "1",
            "2",
            "--report",
            str(cache / "rtdetr.json"),
        ],
        [
            "export_siglip_zeroshot.py",
            "--model-dir",
            str(directory / "siglip-base-patch16-224"),
            "--report",
            str(cache / "siglip.json"),
        ],
        ["export_scene_text.py"],
        ["export_local_prompts.py"],
    ]
    for script, *arguments in commands:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), *arguments],
            cwd=ROOT,
            check=True,
        )
    if (
        json.loads((cache / "rtdetr.json").read_text(encoding="utf-8"))["status"]
        != "passed"
    ):
        raise ValueError("RT-DETR numerical parity check did not pass")
    if not json.loads((cache / "siglip.json").read_text(encoding="utf-8"))["passed"]:
        raise ValueError("SigLIP numerical parity check did not pass")


def install_depth_small(directory: Path, source: Path | None = None,
                        *, verify_only: bool = False) -> None:
    """Optional Apache-2.0 Small checkpoint, separate from production assets."""
    manifest = json.loads(DEPTH_MANIFEST.read_text(encoding="utf-8"))
    if any(m["license"] != "Apache-2.0" for m in manifest["models"]):
        raise ValueError("Only the licensed Small depth model is allowed")
    if verify_only:
        verify_files(source or directory, manifest["runtime_files"])
        print("Optional depth model hashes verified; no network")
        return
    if source is None:
        download_sources(directory, manifest)
    else:
        verify_files(source, manifest["runtime_files"])
        for name in manifest["runtime_files"]:
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if (source / name).resolve() != target.resolve():
                shutil.copy2(source / name, target)
    verify_files(directory, manifest["runtime_files"])
    target = directory / "depth-anything-v2-small/installation_manifest.json"
    target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Optional local depth model ready; production default unchanged")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--source", type=Path, help="Existing canonical exported model bundle"
    )
    modes.add_argument(
        "--download",
        action="store_true",
        help="Pinned upstream sources plus local export; needs export dependencies",
    )
    modes.add_argument("--depth-small", action="store_true",
                       help="Download only optional Apache-2.0 Depth Anything V2 Small")
    parser.add_argument("--depth-source", type=Path,
                        help="With --depth-small: copy/verify an existing model-root bundle")
    parser.add_argument("--output", type=Path, default=ROOT / "models")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Validate --source without copying or network",
    )
    args = parser.parse_args()
    if args.depth_small:
        install_depth_small(args.output, args.depth_source, verify_only=args.verify_only)
        return
    if args.depth_source:
        parser.error("--depth-source requires --depth-small")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if args.verify_only and not args.source:
        parser.error("--verify-only requires --source")
    if args.download and args.output.resolve() != (ROOT / "models").resolve():
        parser.error(
            "--download exports into ml2/models; use --source for a different destination"
        )
    if args.source:
        installed_manifest = args.source / "installation_manifest.json"
        files = manifest["runtime_files"]
        if installed_manifest.exists():
            installation = json.loads(installed_manifest.read_text(encoding="utf-8"))
            if installation.get("source_files") != manifest["source_files"]:
                raise ValueError(
                    "Installed source provenance differs from pinned sources"
                )
            files = installation["runtime_files"]
            if set(files) != set(manifest["runtime_files"]):
                raise ValueError(
                    "Installed runtime asset set differs from the manifest"
                )
        verify_files(args.source, files)
        if args.verify_only:
            print("All model asset hashes verified; no copy, no network")
            return
        for name in files:
            source, target = args.source / name, args.output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
        verify_files(args.output, files)
        manifest["runtime_files"] = files
    else:
        download_sources(args.output, manifest)
        export_local(args.output)
        manifest["runtime_files"] = {
            name: dict(
                sha256=digest(args.output / name),
                size=(args.output / name).stat().st_size,
            )
            for name in manifest["runtime_files"]
        }
        verify_files(args.output, manifest["runtime_files"])
    (args.output / "installation_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print("Local runtime models ready; service never downloads weights")


if __name__ == "__main__":
    main()
