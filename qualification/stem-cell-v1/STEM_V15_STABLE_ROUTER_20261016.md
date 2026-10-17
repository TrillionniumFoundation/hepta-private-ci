# V15 — Stabilize real-feature training before claiming Cell specialization

2026-10-16. **RESEARCH / SHADOW_ONLY / DENY_ALL.** Additive continuation of PR #2364 on inspected parent `ea9bab9f643047fa4a66fc6523b03b0c03f5d7a1`. Its parallel CI de-duplication/packaging change is retained. Original V14 source, V5–V13 evidence, production Rust, selected models, NDU, CAS/CNS, FinalUse and main remain unchanged.

## Evidence and deliberately limited scope

The actual Library copy of original GitHub artifact `11890616195` / run `38546717991` is 1,398,480 bytes, SHA256 `0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7`. It contains the original mmBERT-small `abc32620dd4f6ab06f5fbe905dc25f310618e09f` FP32 128 x 384 feature snapshot and AG News publisher labels. V14 input SHA `d029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a` and feature SHA `e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490` are unchanged.

V15 uses **64 original TRAIN records and 32 previously exposed calibration records**. It seals predictions for the existing 32 blind records but **does not read their labels or report their scores**. The V15 integration test deletes the separate prepared held-label file before actual training. Preparation still sees the full archive, and this is process/data-interface separation, not independent label custody or OS access-control attestation. The inherited V14 regression suite has its own historical label scorer; that is not a new V15 evaluation.

No new Encoder is loaded or executed. The source identity of archived features is checked, not independently authenticated model/host custody. Three seeds reuse exactly the same original rows, not three independent source families. This round measures implementation and calibration behavior, not generalization or future utility.

## Implemented and actually exercised

1. **Stabilization:** freeze a mean from only the first 32 TRAIN rows; subtract it and L2-normalize each row. One shared 384-scalar mean is charged separately. Fold-specific means exclude their evaluation rows. All parameters, seed values, 80 SGD steps, learning rate 0.1 and 16-row batches were fixed in a local pre-execution protocol seal. That seal is not an external preregistration timestamp.
2. **Controls:** reproduce the raw-feature V14 parent/continuation as training diagnostics; separately train normalized frozen, continued, rank-7 wider residual and two-Head centroid models. Wider and split start from the same trained parent outputs. No original selected deployment model is claimed.
3. **Task gate:** build four source-ID-hashed TRAIN folds. For every row, both teacher-expert logits come from models trained without that row, including exclusion from the teacher normalizer and centroid fit. The smaller original-label NLL supplies a binary preference target. Fit one 385-parameter logistic gate using these 64 out-of-fold targets. The final gate takes only features, not task labels. Teacher-fold fitting is real extra work, not free learning.
4. **Counterfactuals:** apply centroid, task gate, swapped and deterministic shuffled routes to the SAME two trained Heads. Actual dispatch computes only selected Head rows. Gate/centroid training and the offline two-expert teacher evaluation are charged separately. The learned gate is a post-training router candidate, not jointly optimized expert topology.
5. **Conservative selector:** calibration-only Brier, a fixed small resident-parameter charge, 0.01 improvement margin and old TRAIN-fit bound. Growing candidates must also beat continuation by the margin. This is a research choice, not NDU or a production promotion gate; old TRAIN fit is not independent retention.

Fold expert slots use a deterministic numerical projection order. That prevents arbitrary index ordering but **does not establish semantic identity across fold models and the final model**. Out-of-fold expert preferences may therefore fail to transfer. This limitation is retained rather than represented as solved credit assignment.

## Actual results — all quality figures below are CALIBRATION, not heldout

Each denominator is the SAME 32 calibration records:

| Profile | Seed 41 correct | Seed 47 correct | Seed 53 correct |
| --- | ---: | ---: | ---: |
| Normalized frozen parent | 10 | 14 | 15 |
| Normalized continued unsplit | 18 | 17 | 17 |
| Normalized wider unsplit | 18 | 16 | 16 |
| Two Heads, centroid route | 18 | 18 | 17 |
| Same Heads, centroid route swapped | 14 | 14 | 14 |
| Same Heads, centroid route shuffled | 18 | 17 | 15 |
| Same Heads, out-of-fold-trained task gate | 11 | 18 | 11 |
| Same Heads, task gate swapped | 21 | 14 | 20 |

Calibration Brier for continuation: **0.595298 / 0.603400 / 0.595785**; centroid: **0.630272 / 0.635403 / 0.628882**; task gate: **0.665629 / 0.664531 / 0.662355**. The prespecified selector chooses **continued / continued / continued**. The task gate has worse Brier than its swapped counterpart at all three seeds. No route winner is promoted after observing these results.

Old-TRAIN parent cross-entropy after the identical 80-step schedule changes from raw **255.3128 / 124.8500 / 140.4622** to normalized **1.074928 / 1.069745 / 1.076132**. This directly diagnoses severe raw-feature optimization behavior and improves this bounded fitting mechanism. It is not a proof of general optimization stability, task generalization, an optimal learning rate or superiority to a large model.

## Physical budgets and full cost qualifications

| Candidate | Trainable scalars | Frozen route scalars | Resident scalars excluding common mean |
| --- | ---: | ---: | ---: |
| Frozen parent | 0 after fitting | 0 | 1540 |
| Continued unsplit | 1540 | 0 | 1540 |
| Wider unsplit | 4267 | 0 | 4267 |
| Centroid two-Head | 3080 | 768 | 3848 |
| Same Heads plus task gate | 3465 in total across stages | 768 | 4233 |

The common normalizer costs 384 scalars once. The wider/task candidate resident gap is 34 scalars, not exact equality of training parameters, gradients, active FLOPs, exposures per expert or whole-life cost. Momentum-free SGD has no momentum state. Cross-fit teacher models and normalizers are research-training artifacts, not extra production experts.

Each complete campaign physically fits **45 parameter bundles**, stores **13 normalizer snapshots** (58 safetensors files total), and performs **3,600 SGD updates**. This includes raw diagnostic fits, all cross-fit teachers and task gates. Each split training loop records 1,280 selected Head-row calls rather than a fictitious 2,560 dense computation count. This is an operator count, not a FLOP measurement.

Two separately launched Linux child processes each completed the whole campaign. Whole-child CPU: **4.533269 / 4.405496 seconds**; wall: **4.536144 / 4.411249 seconds**; wait4 peak RSS: **332,451,840 / 332,382,208 bytes** (about 317 MiB). These include Python/Torch imports, fitting and checkpoint writes, but exclude historical Encoder work, preparation and the separate reviewer. They are not per-arm costs, target-device measurements, inference latency, p99, energy or 4,096-Cell acceptance. The actually executed meter script is retained in the local evidence bundle.

| Candidate | Future utility gain | Independent negative transfer | Per-arm peak RSS | p99 | 4096-Cell throughput | Disposition / no-change baseline |
| --- | --- | --- | --- | --- | --- | --- |
| Frozen normalized parent | Not evaluated | Not evaluated | Not measured | Not measured | Not measured | Research no-change baseline, not deployed A0 |
| Continued normalized parent | Not evaluated | Not evaluated | Not measured | Not measured | Not measured | Chosen on all three calibration seeds only |
| Wider unsplit | Not evaluated | Not evaluated | Not measured | Not measured | Not measured | Not selected; compare to frozen and continued |
| Centroid/task split | Not evaluated | Not evaluated | Not measured | Not measured | Not measured | Not selected; no future or specialization claim |

## Independent replay and tests

Two metered campaigns produced **58/58 identical file SHA256s, 768/768 calibration probability rows, 768/768 unscored blind probability rows and 1,536/1,536 out-of-fold teacher logits**. These counts are repeated computations of the same original rows, not new samples.

The separate reviewer imports neither Torch nor the producer. It reconstructs source folds, excluded-row means, centroid identities, all tensor shapes/counts, teacher logits and targets, calibration and blind probabilities, old-TRAIN Brier and the research selector. Maximum absolute numerical difference across checked logits/probabilities: **3.2782554626464844e-07**, with zero top-class flips. It checks training work fields but does not independently replay gradients, prove an honest physical host, or authenticate a label issuer.

**36/36 V15 tests pass normally and under python -O; 66/66 combined V14+V15 tests pass in both modes; zero skips with the original archive mounted.** Sixteen V15 mechanism tests use explicit synthetic tensors; twenty integration/tamper tests use the actual archived features. Tests reject rehashed wrong fold normalizers, wrong teachers/targets, modified weights, routes, calibration, selected candidates, counts, protocol and false authority/future claims. Python compilation and all six inherited/extended workflow Bash blocks pass local syntax checks. Full repository formatter/Clippy/security/Architecture and exact new-head hosted CI are separate, unverified gates.

The existing V14 workflow is extended rather than adding another parallel CI workflow. Its original commands, exact checkout and separate PR/push concurrency remain. PR checks include V15 mechanism tests; the original-archive push path additionally trains and independently reviews V15, uploading only the aggregate review. The public Git tree contains no raw passages, feature matrices, model checkpoints, blind probabilities or case-level teacher targets.

## Reproduce on the original immutable material

```bash
cd qualification/stem-cell-v1
export HEPTA_V14_ORIGINAL_ZIP=/private/hepta-public-pretrained-38546717991.zip
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python -m unittest -v test_stem_counterfactual_split_v14 test_stem_stable_router_v15
python -O -m unittest -v test_stem_counterfactual_split_v14 test_stem_stable_router_v15
python stem_counterfactual_split_v14.py prepare \
  --archive "$HEPTA_V14_ORIGINAL_ZIP" --out /private/v15-input \
  --labels-out /private/do-not-use-v15-held-labels.json
python stem_stable_router_v15.py --inputs /private/v15-input --output /private/v15-run
python stem_stable_router_v15_review.py --inputs /private/v15-input \
  --candidates /private/v15-run --output /private/v15-reviewed.json
```

**Decision:** retain the simpler continuation research candidate. Before more Cells, investigate stable expert identity and joint task/router learning with charged training costs, then obtain untouched source-disjoint evaluation. No held score, prospective utility, learned general intelligence, giant-model equivalence, original production CellSplit, FinalUse permission or main merge is established here.
