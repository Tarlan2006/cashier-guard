"""Optional local-only Depth Anything V2 Small; never loaded by default."""
from pathlib import Path
import json
import os
import time
import cv2
import numpy as np


class LocalDepthSmall:
    def __init__(self, directory: str | Path, *, device: str = 'cpu', threads: int = 2):
        started = time.perf_counter()
        os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
                          HF_HUB_DISABLE_TELEMETRY='1')
        import torch
        from transformers import DepthAnythingForDepthEstimation
        from transformers.models.dpt.image_processing_pil_dpt import DPTImageProcessorPil
        from scripts.download_models import verify_files, DEPTH_MANIFEST
        directory = Path(directory).resolve()
        manifest = json.loads(DEPTH_MANIFEST.read_text(encoding='utf-8'))
        verify_files(directory.parent, manifest['runtime_files'])
        torch.set_num_threads(threads)
        torch.manual_seed(42)
        self.torch, self.device = torch, device
        self.processor = DPTImageProcessorPil.from_pretrained(str(directory), local_files_only=True)
        self.model = DepthAnythingForDepthEstimation.from_pretrained(str(directory), local_files_only=True).to(device).eval()
        self.load_sec = time.perf_counter()-started

    def predict(self, image_bgr: np.ndarray) -> tuple[np.ndarray, float]:
        started = time.perf_counter()
        inputs = self.processor(images=cv2.cvtColor(image_bgr,cv2.COLOR_BGR2RGB), return_tensors='pt')
        inputs = {k:v.to(self.device) for k,v in inputs.items()}
        with self.torch.inference_mode():
            raw = self.model(**inputs).predicted_depth
            result = self.torch.nn.functional.interpolate(raw[:,None], size=image_bgr.shape[:2], mode='bicubic', align_corners=False)[0,0]
        if self.device.startswith('cuda'):
            self.torch.cuda.synchronize()
        return result.cpu().numpy(), time.perf_counter()-started
