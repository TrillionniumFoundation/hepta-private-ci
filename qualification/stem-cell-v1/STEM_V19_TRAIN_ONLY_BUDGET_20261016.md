# V19 — Real mmBERT frozen-feature TRAIN-only budget selection (negative / exploratory)

**2026-10-16 · Research-only · DRAFT · SHADOW_ONLY · DENY_ALL.** This additive branch starts at the exact #2481 research HEAD \`cbf76715db6e3c31ad7e3edab138d1b2fcd36859\`; it does NOT update the original V18 branch, main, an Encoder/Reader model, Worker, NDU, CellSplit, CNS, CAS, signer, FinalUse or a deployed user host.

## Why this investment test

On the previously examined original 32-case AG News historical CAL panel, cold-start Head training beyond 4–8 updates often fits TRAIN better while degrading the original CAL Brier. That historical observation motivated this test. **The budget set, choice tolerance, and technique were designed after seeing that old CAL panel; do not pretend the outcome is an untouched future evaluation.** The question here is whether a selection policy using only TRAIN record labels can identify an economical checkpoint, and whether the source/weight/output arithmetic is reproducible in an independent framework.

## Immutable source identity

- Original GitHub Actions run [38546717991](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38546717991), artifact **11890616195**, exact original ZIP SHA256 \`0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7\`.
- Frozen original \`jhu-clsp/mmBERT-small\` pretrained **cached** 128x384 FP32 Feature material, exact original safetensors \`e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490\`.
- Original V14 source-only prepared \`input.json\` exact SHA256 \`d029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a\`; **64 original TRAIN rows, 32 previously exposed CAL, 32 unscored BLIND**.
- Original source only; there are **not** four independent task families. The four held-TRAIN folds all come from **one AG News dataset family**; row-ID SHA-based fold construction is label-agnostic but global TRAIN feature normalization observes all TRAIN feature values. No new original Encoder calls or a newly authenticated publisher signature are created here.

## Physically executed learning design

Each of seeds 41, 47, 53 obtains one independent zero-initialized 1,540-parameter FP32 linear Head per TRAIN fold, trained on 48 original rows, with 16 source-disjoint held-fold TRAIN labels used only to choose checkpoints. Four complete **80-step** TRAIN-only physical SGD/Adam paths are executed per seed, preserving intermediate actual checkpoints at **1, 2, 4, 8, 16, 32, 80** updates. For each candidate budget, every original TRAIN row has exactly one out-of-fold prediction from a model that did not train on that row's label. The selection rule is **smallest budget with OOF multiclass Brier no more than 0.02 above the seed's best OOF Brier**. The 0.02 tolerance is a registered *engineering candidate*, not a significance interval or verified dollar price.

After selection, an independently zero-initialized Head executes **80 actual full-TRAIN** updates per seed under the same original V18 per-seed schedule. Historical CAL and blind outputs are produced at all seven checkpoints, but **CAL labels never enter the TRAIN-only budget selection, BLIND labels are never scored or used**. The 32 CAL labels were already exposed in previous research, so the reported CAL comparison is explicitly exploratory, not a scientific holdout.

The research actually paid **4 folds × 80 training updates + 80 full training updates = 400 physical Head updates per seed**, or **1,200 total**. This is much greater total observed pilot/training work than simply running an 80-step no-change Head at each of three seeds (240 updates). It would be incorrect to claim 10–20x complete online cost savings from the smaller final checkpoint alone. External data acquisition, pretrained Encoder inference/Reader, independent host signatures, durable provenance, replay state, WAL and target-host CPU/RSS/p99 remain separately unpriced.

## Original data descriptive results

Multiclass Brier lower is better. Selection uses original 64-row TRAIN-only OOF scores; CAL is the same exposed 32-case historical panel.

| Seed | TRAIN-only OOF chosen steps | OOF Brier at choice vs 80 | Historical CAL correct chosen vs 80 | Historical CAL Brier chosen vs 80 |
| --- | ---: | --- | --- | --- |
| 41 | **8** | **0.430970 vs 0.443349** | **21/32 vs 24/32** | **0.447244 vs 0.437980** |
| 47 | **4** | **0.418765 vs 0.422627** | **25/32 vs 24/32** | **0.323842 vs 0.434068** |
| 53 | **8** | **0.505349 vs 0.510515** | **27/32 vs 24/32** | **0.266172 vs 0.437576** |

The OOF selector **harms** Seed 41 CAL correctness, and Seed 47's 4-step OOF count (45/64) is *below* 80 steps (48/64) even though its OOF Brier is lower. These results show a realistic accuracy/calibration tradeoff, not a universal winner. TRAIN-only cross-validation across 64 same-family records and three random seeds is not equivalent to independent future-task generalization. **No deployment, automatic checkpoint switch, autonomous Cell training or CellSplit is permitted.**

## Original physical verification and independent review

Original source files were available in an isolated CPU analysis environment, using PyTorch CPU 2.10.0, NumPy 2.3.5 and safetensors 0.7.0. The actual, byte-pinned code physically retrained two separate processes: normal Python and \`python -O\`. Both reproduced **105/105 source-case-bound physical model/forward SHA identities** (4-fold × 7 checkpoints × 3 seeds + one final model × 7 checkpoints × 3 seeds), all three TRAIN-only choices and all historical CAL scores. The separate independent NumPy reviewer imports **neither Torch nor producer**, independently reopens the immutable feature file/roster, recalculates FP32 normalization and every Head's source-specific linear output from **its original checkpoint parameters**, recomputes OOF/CAL metrics, and validates all 105 state/output hash pairs. It does **not** independently rederive optimizer gradients, cryptographically authenticate publisher/host, or score the original BLIND labels.

- 11/11 source-only mechanism/negative tests in normal and optimized Python; 11/11 authentic original-material tamper/forward tests in normal and optimized Python. **44 test executions total** with real original material staged for the latter 22.
- Source/weight/output identity tampering, even with rehashed one-sided payloads, incorrect case order, fake new windows, missing checkpoints, altered scores, fake authority, and zero/nonmonotonic physical CPU receipts fail closed.
- Local complete public aggregate SHA256 \`6b82582a62d8884ccab0474e4a92dd19b754518690a03963b0ad600748a1cbeb\`. The independently rederived review JSON SHA256 \`a22dab7be3af4a5791798a81d4ed3225c2bb7a35d421eb247d59dd97398b82bb\` is identical between ordinary and optimized runs (physical CPU counters in producer aggregate necessarily differ).
- Public repo includes only source/test/CI/sanitized observations. No source text, labels, raw features, private per-case IDs, logits, checkpoint weights or private predictor traces are uploaded.

## Reproduction and strict hosted gates

Retrieve only the exact SHA-pinned original GitHub artifact 11890616195 and verify ZIP SHA, then create a private, create-only prepared directory with the inherited original \`stem_counterfactual_split_v14.py prepare\`. Delete the separately created BLIND label file without passing it to model training or reviewer. From \`qualification/stem-cell-v1\`:

\`\`\`sh
python -m unittest -q test_v19_budget
python -O -m unittest -q test_v19_budget
python v19_train_only_budget.py --inputs /private/inputs --output /private/v19-result.json --private /private/v19-checkpoints.json
python v19_independent_numpy_review.py --inputs /private/inputs --report /private/v19-result.json --private /private/v19-checkpoints.json --output /private/v19-independent.json
HEPTA_V19_INPUTS=/private/inputs HEPTA_V19_REPORT=/private/v19-result.json HEPTA_V19_PRIVATE=/private/v19-checkpoints.json python -m unittest -q test_v19_original_replay
\`\`\`

The exact-head GitHub workflow \`hepta-stem-v19-trainonly-original.yml\` independently acquires the original artifact with an authenticated GitHub API request, downloads the HTTPS redirected ZIP without forwarding GH_TOKEN, checks its full SHA256, and executes two physical processes plus independent review/tests. No private artifacts are published to Git. A queued workflow is not a passed workflow. Full architecture, blocking-ci, source/current-base merge and independent operator review continue to gate any engineering integration.

**Disposition: RESEARCH_HISTORICAL_ONLY_DENY_ALL.** Next actual science requires new independent source families, external label custody, two genuine prospective windows, strong unchanged baseline, loss/negative-transfer accounting, and full lifecycle cost; production 64–4096 Cell physical target-host performance/recovery remains unmeasured here.
