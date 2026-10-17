# v6: video-level rule validation and weakly supervised zones

Date: 2026-10-17T20:02:25; seed=42; CPU; Python 3.12.

40 unique MD5 groups: 21 violation-labelled and 19 normal. Duplicate clips are evaluated as one group, retaining all reference times locally. Input facts are the existing v5 production facts; all 40 were reevaluated by the new track rules without image inference or labels in runtime code. The long-video timing is a separate fresh, uncached full perception run.

## A1/A2: independent video-level and timestamp metrics

Gate: TP >= 3 and FP <= 1 on normal videos. Reference-time error is descriptive only. For each detected positive video it is the minimum absolute distance between any emitted onset and any reference time; MAE averages those per-video minima. Missed videos are excluded from MAE and remain FN. This optimistic nearest-event statistic does not establish correct event type. The gate is an in-sample development screen, not an independent generalization estimate.

| Rule | TP /21 | FP /19 | FN | TN | Onset MAE, s | Enabled | Source |
|---|---:|---:|---:|---:|---:|---|---|
| cashier_away_with_client | 0 | 0 | 21 | 19 | — | no | v6 tracks only |
| cashier_left_workplace | 12 | 8 | 9 | 11 | 3.54 | no | v6 tracks only |
| cashier_returned_workplace | 0 | 0 | 21 | 19 | — | no | v6 tracks only |
| three_people_at_table | 2 | 1 | 19 | 18 | 9.00 | no | v6 tracks only |
| two_clients_three_seconds | 2 | 1 | 19 | 18 | 9.00 | no | v6 tracks only |
| items_after_cashier_left | 0 | 0 | 21 | 19 | — | no | v5 reference only |
| previous_items_with_new_client | 0 | 0 | 21 | 19 | — | no | v5 reference only |
| safe_open_while_working | 0 | 0 | 21 | 19 | — | no | v5 reference only |
| unlocked_laptop_after_cashier_left | 0 | 2 | 21 | 17 | — | no | v5 reference only |

Global settings: track presence hold=3 s, departure/return confirmation=2 s; initial workplace from the first 3 s of cashier observations; radius=0.5 torso short side, clamped to 0.035–0.15 image diagonals; departure boundary=1.15 radius; reidentification is unchanged. Reflections and uncertain tracks are excluded. Detection gaps over 1 s never prove continuous presence. Once a track is confirmed, onset is backdated to its actual observations, never to the confirmation time. No thresholds were selected per video.

The four zero-shot state rows are retained solely as the previously computed v5 baseline; they are not a v6 linear-classifier evaluation and cannot be enabled by this report. An overlap true positive may have a different annotated issue: binary TP is not rule-type correctness.

### Private per-video results

Per-video labels and timecodes remain in the local ignored evaluation cache. Only aggregate metrics are published.

## A3: logistic regression on frozen SigLIP zone crops

One fixed configuration: StandardScaler + LogisticRegression(C=0.1, class_weight=balanced, max_iter=2000, random_state=42). Scaling and classifier fit exclusively on training MD5 groups; leave-one-video-out; no hyperparameter search. Frozen SigLIP was not fine-tuned. Before frames at -2/-1 s were extracted but explicitly left unlabeled: the PDF does not establish their state. After samples use 0/+0.5/+1 s. Paired controls use the same reference seconds, clamped to the clip's last available frame; no hand-adjusted offsets. A normal control that describes an object being received is excluded as an empty-table label. Other cleanup controls remain weak episode labels, not verified frame annotations. Duplicate clips are used once. There is no defensible frame-state ground truth in this source.

| Zone | Unique videos | Labelled frames | LOVO evaluated | Accuracy vs weak labels | Majority baseline | Normal videos with positive output |
|---|---:|---:|---:|---:|---:|---|
| table | 9 | 27 | 27 | 25.9% | 55.6% | 4/4 |
| safe | 2 | 6 | 0 | not evaluable | 50.0% | not evaluable |

Table classification is worse than the majority baseline and provides no useful evidence. A positive object state on a normal video is not by itself a violation; the last column is the requested normal-video alarm proxy, not a validated downstream FP count. Safe has only one open and one closed video; each held-out fold has a single training class, so accuracy/FP are unavailable, not zero. Both experimental numeric heads were fitted for reproducibility and kept only in ignored cache. The runtime adapter supports numeric linear heads and has no zero-shot fallback; no state rule is enabled.

## A4/A5: publication and fresh long-video timing

No rule passes the gate. configs/rule_validation.json records the measurements and an empty whitelist. analyze_video emits no rule events; analyze_report explicitly returns partial and a null verdict when coverage is insufficient. A processing failure in the list-only API raises AnalysisIncomplete instead of returning an empty list. HTTP packaging must preserve errors as non-2xx responses.

| Input | Duration, s | Full wall time, s | Under 170 s | Sampling changes | Cache |
|---|---:|---:|---|---|---|
| Open 14 + same clip, video-only reencode | 285.07 | 103.84 | yes | [] | no |

The source's measured duration differs from the rounded 145 s in the task; the concatenation is ~285 s. This run finishes before the 150 s adaptation threshold, so no step increase is necessary. The configured schedule is 0.5 s before 150 wall seconds, then 2–10 s adaptively; soft stop=168 s, outer deadline=170 s (1 s cleanup reserve). Existing fake-clock and real hung-worker tests exercise adaptation and forced termination. This single latency measurement is not a worst-case guarantee.

## Weak points / next actions

- Pure departures also occur in normal scenes; tracks cannot identify cash/documents left on a desk.
- Two-client overlap also fires on a normal control and detects only two positive-labelled videos, one with a different issue.
- Role and anchor errors remain; candidate availability must not be confused with accuracy.
- No operational door detector or verified table segmentation; workstation origin and height are geometric proxies.
- Accurate before/after state labels and independent held-out scene groups are required before training can be assessed.
- No closed-test frames, VLM, cloud AI, per-video runtime exceptions or private media/labels were committed.

Reproduce: python eval/v6_tracks.py; python eval/v6_zones.py; python eval/v6_long_video.py; python -m unittest discover -s tests; python eval/v6_report.py. Evaluation requires the ignored open data, manual labels, v5 facts and local model weights.

## Stage B: repository transport check

Packaged checks: 134 tests passed; pip check passed. Runtime assets verified against SHA-256 without copying weights into the repository. Network download/export mode was not repeated. Protected directories and the working catalog were unchanged.

Python 3.12.10 ML1, Python 3.14.7 backend; local port 8001; matching stub on 8002. Source workspace commit: d740d93. No rule passed the v6 gate.

| Видео | Прямой ML1, с | Полная цепочка HTTP/poll, с | ML1 внутри backend, с | Итог |
|---|---:|---:|---:|---|
| 2 | 15.46 | 15.49 | 15.25 | done / no_violation |
| 14 | 49.18 | 50.34 | 50.02 | done / no_violation |

Это тест транспорта с заглушкой matching и пустым whitelist правил. Оба ответа ML1 проверены по текущей JSON Schema; истинность вердикта по видео не проверяется. Модели загружены по одному разу; кэш признаков сбрасывается между запросами, что отражено заголовком X-Input-Cache. Повреждённый MOV вернул HTTP 422, а не пустой успешный ответ. Логи и исходные JSON находятся только в игнорируемом cache/integration_final/.

The repository default rules catalog is empty and initially produced RULES_EMPTY; the successful transport check uses a local structural conversion of the team research catalog without modifying its source or data/rules.json. Production applicability remains with participant 4. See ../../INTEGRATION.md for timeout changes and the backend partial-status mismatch.
