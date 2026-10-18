"""Frozen RT-DETR R18 backbone features from already pinned local weights; CPU only."""
import gc,hashlib,os
from pathlib import Path
import cv2,numpy as np

class FrozenDoorFeatures:
 def __init__(self,directory,threads=2):
  os.environ.update(HF_HUB_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',DO_NOT_TRACK='1')
  import torch
  from transformers import RTDetrForObjectDetection
  directory=Path(directory);weights=directory/'model.safetensors'
  digest=hashlib.sha256(weights.read_bytes()).hexdigest()
  if digest!='fe87a5a30f5daf298d10794c7682a63b6107986f97d6a770ba948d89e4340093':raise ValueError('Unexpected backbone weights')
  torch.set_num_threads(threads);torch.manual_seed(0)
  detector=RTDetrForObjectDetection.from_pretrained(directory,local_files_only=True).cpu().eval()
  self.backbone=detector.model.backbone.model.eval()
  for parameter in self.backbone.parameters():parameter.requires_grad_(False)
  del detector;gc.collect();self.torch=torch
  self.spec={'kind':'frozen_RTD ETR_R18_backbone'.replace(' ',''),'weights_sha256':digest,'revision':'ac77a11ff0170a41b771c03264987f8ce2b0d753','input':[224,224],'preprocessing':'BGR_to_RGB; bilinear_resize; divide255; no_mean_std_normalization','pooling':'global_average_and_2x2_average_grid_per_stage; each_stage_L2_normalized','backbone_trained_here':False,'device':'cpu','torch_threads':threads}
 def feature(self,image_bgr):
  if image_bgr is None or image_bgr.size==0:raise ValueError('Empty crop')
  torch=self.torch;rgb=cv2.cvtColor(image_bgr,cv2.COLOR_BGR2RGB);rgb=cv2.resize(rgb,(224,224),interpolation=cv2.INTER_LINEAR)
  tensor=torch.from_numpy(np.ascontiguousarray(rgb.transpose(2,0,1))).float().unsqueeze(0)/255.
  with torch.inference_mode():
   maps=self.backbone(tensor).feature_maps;features=[]
   for m in maps:
    pooled=torch.cat([torch.nn.functional.adaptive_avg_pool2d(m,1).flatten(),torch.nn.functional.adaptive_avg_pool2d(m,2).flatten()]);pooled=pooled/pooled.norm().clamp_min(1e-8);features.append(pooled)
   result=torch.cat(features).cpu().numpy().astype(np.float64)
  if not np.isfinite(result).all():raise ValueError('Nonfinite features')
  return result
