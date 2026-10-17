# Models used in stage 1

Recorded: 2026-10-17. No external inference APIs are used.

| Model | Exact version | License | Use |
| --- | --- | --- | --- |
| `google/siglip-base-patch16-224` | Hugging Face revision `7fd15f0689c79d79e38b1c2e2e2370a7bf2761ed` | Apache-2.0 | Local image embeddings at 224 x 224, normalized to unit length |
| Logistic regression (`sklearn.linear_model.LogisticRegression`) | scikit-learn 1.9.1; `C=1.0`, balanced class weights, `max_iter=2000`, seed 0 | BSD-3-Clause (scikit-learn implementation) | Trained locally inside each of five GroupKFold splits by file MD5; no downloaded classifier weights |

SigLIP license evidence: the downloaded model card declares `license: apache-2.0`.
Source: [versioned model card](https://huggingface.co/google/siglip-base-patch16-224/blob/7fd15f0689c79d79e38b1c2e2e2370a7bf2761ed/README.md).
The snapshot, including the source card, is stored locally in
`models/siglip-base-patch16-224/` (ignored by Git).

Only SigLIP's image features are used. No audio, face recognition, cloud
inference, person detector, or VLM is used in stage 1.

Extraction uses PyTorch 2.14.1+cpu and Transformers 5.20.1. The latter returns
an output object from `get_image_features`; extraction reads `pooler_output`
before the existing normalization. This is an API compatibility fix.
`AutoImageProcessor` loads the same image preprocessing without initializing
an unused text tokenizer (which would otherwise require SentencePiece).

## Controlled diagnostics, 2026-10-17 (diagnostics-v1)

| Model | Exact version | License | Use |
| --- | --- | --- | --- |
| PCA (`sklearn.decomposition.PCA`) | scikit-learn 1.9.1; 32 or 64 components; randomized SVD, seed 0 | BSD-3-Clause | Separate ablations on the original 1536-dimensional emb+diff features. Fit only on retained training-fold frames; no whitening or other simultaneous feature change. |
| Logistic regression | scikit-learn 1.9.1; C=1, 0.1 or 0.01, otherwise baseline settings | BSD-3-Clause | Separate C ablations and a duration-only control, all evaluated inside the same five MD5 folds. |

Diagnostics reuse the existing local SigLIP embeddings at the original frame
rate. No new weights, VLM, cloud inference, face recognition, or audio models
are used. The deployed pipeline and original baseline are not replaced by an
ablation winner.

## Local perception, 2026-10-17 (perception-v1)

| Model | Exact version | License | Use |
| --- | --- | --- | --- |
| `PekingU/rtdetr_r18vd` | Hugging Face revision `ac77a11ff0170a41b771c03264987f8ce2b0d753` | Apache-2.0 | Frozen local COCO person/object detection; no fine-tuning or calibration training |

License evidence: [versioned downloaded model card](https://huggingface.co/PekingU/rtdetr_r18vd/blob/ac77a11ff0170a41b771c03264987f8ce2b0d753/README.md)
declares `license: apache-2.0`. Weights and card are kept locally in
`models/rtdetr_r18vd/` (ignored). No Ultralytics components are used.

Reference runtime: Transformers 5.20.1, PyTorch 2.14.1+cpu. The input is configurable;
the CPU profile uses 384 x 384 rather than the snapshot's default
640 x 640, batch 1, 2 threads, FP32. This is inference configuration,
not training. The frame grid stays at 0.5 s. A PyTorch channels-last equivalence check
on a local sample gave maximum differences of 0.0001231 for logits and
0.00000252 for normalized boxes (rtol 1e-3, atol 5e-4 passed).

The default CPU backend is ONNX Runtime 1.31.0 (MIT implementation); ONNX
1.23.2 is used only for the one-time local export. `model_384.onnx` is a
fixed-input FP32 conversion of the same frozen Apache-2.0 weights, not a
trained or quantized model. Export uses opset 17. SHA-256:
`d777f785af36550779f3227d358db8fac458e341de417312ee37543808609ffc`.
Raw logits and boxes were checked against PyTorch on three real local frames
with rtol=1e-3 and atol=1e-3. Results/provenance are stored in ignored
`cache/perception-onnx-export-384.json` and the model directory.
The NumPy/PIL runtime preprocessing was separately checked against the pinned
AutoImageProcessor on the same three timepoints; maximum absolute input error
was 5.960464477539063e-8 (atol=1e-7, rtol=0 passed). This check is recorded in
`cache/perception-preprocessing-validation.json`.

The initial PyTorch long-video run exceeded the 300 s hard budget, so the
lighter CPU runtime was necessary. PyTorch remains an explicit optional
backend for a GPU host; there is no automatic runtime download or export.

Tracking uses geometry, Hungarian assignment and short motion prediction;
there is no learned re-identification model or face recognition. Role candidates
use optional calibrated counter geometry, not image pixel zones. No counter
detector or banknote recognition model is included.

## Local fixture naming, 2026-10-17 (perception-v2)

| Model | Exact version | License | Use |
| --- | --- | --- | --- |
| `google/siglip-base-patch16-224` | Same pinned revision `7fd15f0689c79d79e38b1c2e2e2370a7bf2761ed` | Apache-2.0 | Frozen image/text similarity for at most three oriented crops of each temporally fixed object proposal; six explicit names plus separate rejection prompts |

No new weights were downloaded, no model was trained and no VLM was added.
The source license evidence is the pinned model card linked above. CPU runtime
uses ONNX Runtime 1.31.0 and a fixed FP32 vision encoder exported locally with
PyTorch 2.14.1+cpu / Transformers 5.20.1, ONNX opset 17, input 1x3x224x224.
The text model is used only during the offline export to save normalized prompt
vectors; runtime does not load it or import PyTorch. Tokenizers 0.23.3
(Apache-2.0) reads the already local tokenizer.json for that export.

Derived artifacts (ignored in `models/siglip-base-patch16-224/`):

- `vision_224.onnx`, 371,694,031 bytes, SHA-256
  `c90b8dce0d13ed0019ec641be335ab225874c63da394c7ec715dc3829fc19480`.
- `fixture_text_features.npz`, SHA-256
  `17a1aa24806bd84f40906b833f2947281095dcd2b355dc22a340d24379a6f8ea`.

Three real local crops were processed only on this machine. NumPy/PIL
preprocessing matched the pinned image processor exactly (maximum input
error zero). Normalized ONNX features differed from PyTorch by at most
2.09e-7, passing rtol=1e-3, atol=1e-4. Export provenance and validation are in
ignored `cache/siglip-zeroshot-export.json`. The initial graph export took
7.284 s; validation used CPU two threads. No image content was uploaded.

The permitted emitted names are counter_machine, laptop, phone, monitor, bag
and cash_register. Separate glass/surface/other text prompts permit rejection
as unclassified_fixture; a glass crop is never forced into one of six names.
Raw COCO classes are preserved as provenance, never used as fixed-object
ground truth. Acceptance thresholds and multi-view agreement are global
heuristics; similarity scores are uncalibrated and names can remain unknown.
Reflection filtering, tracking and positional role rules add no learned models.

## Scene corrections, 2026-10-17 (perception-v3)

The two model names, source revisions, Apache-2.0 licenses, FP32 ONNX graphs
and prompt vectors above are unchanged. No weights or dependencies were added.
RT-DETR additionally proposes small objects in three temporal views using
overlapping half-frame tiles; SigLIP checks common crop-context scales
1.0/1.3/1.6 and supplies glass-like context evidence. The primary person
timeline stays at 0.5 seconds. Geometric duplicate suppression, fragment
joining, two-second confirmation, NCC visibility checks and residence-based
role candidates are deterministic local code, without model training.
Open-dataset debug sheets were inspected with the user's explicit development
permission. Service inference remains fully local; closed-test images were
neither inspected nor transmitted.

## Scene anchors and roles, 2026-10-17 (perception-v4)

The RT-DETR and SigLIP names, pinned source revisions, Apache-2.0 licenses and
ONNX vision graphs above are unchanged. No weights were downloaded or trained.
The new `scene_text_features.npz` uses the existing frozen SigLIP text weights
for machine/safe/laptop/phone plus glass/surface/other/bag/monitor rejection.
SHA-256: `6c96223f4582b2beceff90cd47d9d63dfbf62b9a81432e07dc180313ff57edbe`.
Unchanged prompt vectors match the previously validated full-model export
exactly (maximum absolute error 0). No missing text-model parameters were
allowed. The runtime shares the same existing ONNX vision session, without
loading a text encoder or importing Torch. Text export is offline/local-only;
provenance is in ignored `cache/scene_text_export.json`.

Feature softmax roles, onset timestamps and the state engine add no models.
Weights/temperature are configurable heuristics, not trained/calibrated role
probabilities. `pypdf==6.12.2` is a local evaluation dependency for text/color
extraction from the supplied annotation PDF; it is not an inference model.
No images or contact sheets were opened or transmitted in this 40-video audit.

## Temporal facts and semantic states, 2026-10-17 (perception-v5)

RT-DETR `PekingU/rtdetr_r18vd` revision
`ac77a11ff0170a41b771c03264987f8ce2b0d753` (Apache-2.0) and SigLIP
`google/siglip-base-patch16-224` revision
`7fd15f0689c79d79e38b1c2e2e2370a7bf2761ed` (Apache-2.0) are unchanged.
No new weights, dependencies, training or VLM. The existing local SigLIP text
encoder exported 57 fixed prompt vectors for anchors and table/safe/laptop
states into `local_prompt_features.npz`, SHA-256
`0295ffe6cbc7c67997508d7ebb8e064f4df55e3b87ee50376e8de097a7cbce4a`.
Export script: `scripts/export_local_prompts.py`; provenance:
ignored `cache/v5/text_export.json`. Previously existing prompt vectors match
exactly (maximum absolute error 0); runtime uses the shared local ONNX vision
encoder, without a text encoder, Torch import or network requests.
Prompts are recorded in `backend/pipeline/prompts/zone_states.txt`.

HSV clothing histograms omit the top 35% of each person box; they are simple
color statistics, not a learned appearance or face model. Temporal role scores
and semantic margins are uncalibrated heuristic outputs. All thresholds apply
to every video; video numbers, human labels and reference times are confined
to evaluation. No images or contact sheets were opened or transmitted during
this iteration; all decoded open-data pixels stayed in local CV inference.

## Zone logistic experiment, 2026-10-17 (v6)

Frozen SigLIP revision and Apache-2.0 license are unchanged. Local linear heads use scikit-learn 1.9.1 (BSD-3-Clause implementation), LogisticRegression C=0.1 and seed 42. They were fitted only on open-set weak episode labels, with StandardScaler and classifier refit inside each leave-one-MD5-video-out fold. No pretrained encoder was fine-tuned. Numeric coefficients are in ignored cache/v6/zones, not shipped or enabled: table LOVO agreement is below majority chance; safe has too few independent labelled videos. LinearZoneModel has no zero-shot state fallback. No VLM or new pretrained model was added.
