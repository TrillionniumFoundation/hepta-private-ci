# V17 — Verify whether Cell identity alignment produces useful specialist routing

2026-10-16 · **DRAFT / SHADOW_ONLY / DENY_ALL** · TrillionniumFoundation/hepta-private-ci · PR #2364. No main merge or production Cell model, artifact/CAS, original Control/CNS, NDU, signed FinalUse, Worker, or deployed routing change.

## What this experiment closes

V15 cross-fold targets agreed with V16 final expert identities for only 22–25 of the same 64 TRAIN rows; yet direct in-sample loss routing and joint Head/router training still lost against a stronger `extra_continued` single Head. V17 tests whether a *per-fold expert-name permutation* explains the failure. No additional Encoder computation, no changed original training rows or previously frozen V15/V16 weights, and no access to 32 historical held-label annotations are permitted.

The original source material is the previously archived `jhu-clsp/mmBERT-small` real FP32 feature matrix from GitHub Action run **38546717991**, Artifact **11890616195** (original ZIP SHA-256 `0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7`). Its dataset/model publisher identities, source rows and cached 128×384 features are inherited exactly from V14/V15/V16; no synthetic-input fallback. Only 64 original TRAIN records generate teacher-target labels; the same 32 previously exposed CALIBRATION records are scored, and another 32 feature records are stored as blind predictions **without any blind labels or scores**. Three seeds all reuse these exact observations and are not new independent data or calendar windows.

## Prespecified training-only comparison

The experiment uses *each saved, physically fitted V15 fold expert* and 48 complement-TRAIN anchor records for identity matching. Fold teachers have never used their own 16 held-TRAIN labels when fitting. Two alignments are predeclared, both label-free at alignment time:

- **Geometric:** compare the fold's and full-TRAIN frozen centroid route assignments on the 48 TRAIN anchors (using their corresponding frozen normalizers), selecting the permutation with strictly more agreement; equal agreement preserves the original order. The full-TRAIN centroid depends on all original TRAIN **features**, but not on the held fold labels.
- **Logit-reference diagnostic:** compare the squared differences between fold experts and the final V15 experts on the same 48 TRAIN anchors, selecting the lower-cost permutation; ties do not flip. **The final V15 experts were fitted using all 64 TRAIN labels, including the excluded fold. This arm is not statistically independent OOF; it measures reference-dependent naming only, never an independent efficacy gain.**

For each seed, train **three new 385-scalar logistic gates** from the identical zero initialization, same SHA-fixed 80×16 TRAIN-only batch schedule and SGD LR 0.1: original V15 out-of-fold targets, geometry-aligned targets, and logit-reference-aligned targets. The original V15 and V16 frozen experts and the strong V16 extra-continued single Head are byte-preserved. At inference, use *physical selected-Head Top-1 dispatch*; no expert-shared soft inference or changed exposed CAL labels. Geometric/logit inversions and shuffled routes form negative controls.

Only the fixed calibration-only selector may choose a router: it must beat the **V16 `extra_continued`** baseline by more than 0.01 Brier, and must not worsen the 32 old TRAIN rows by more than 0.01 Brier. The latter is not independent old-task retention. There is no production promotion regardless of the selector output; all additional gate fitting and underlying V15/V16/Encoder lifecycle costs remain explicitly chargeable.

## Actual original-feature results — Brier lower is better

All columns are the **same previously exposed 32 CALIBRATION cases**, not genuine future tasks.

| Candidate | Seed 41 | Seed 47 | Seed 53 |
| --- | ---: | ---: | ---: |
| V16 extra-trained **single Head** | **0.546142** | **0.544609** | **0.558352** |
| V16 final-expert loss gate | 0.577418 | 0.562788 | 0.591583 |
| V15 centroid route | 0.630272 | 0.635403 | 0.628882 |
| V17 unaligned OOF gate, matched schedule | 0.673563 | 0.664357 | 0.676625 |
| V17 geometry-aligned OOF gate | 0.665745 | 0.652299 | 0.665479 |
| V17 logit-reference-aligned gate | 0.665745 | 0.652299 | 0.665479 |
| V17 geometry-aligned **swapped** | 0.619814 | 0.633055 | 0.617671 |
| Best single expert, fixed Head 1 | 0.619814 | 0.623929 | 0.617671 |
| Infeasible per-example CAL-label oracle | 0.536395 | 0.534265 | 0.530217 |

**Selection: extra-trained single Head in all three seeds.** Even the new aligned gates collapse toward selecting a constant expert for many cases, and flipping the route is better than the proposed aligned route. The oracle uses true CAL labels after inference and is a *nondeployable post-label upper bound*, not a trainable policy. It offers only about 0.010/0.010/0.028 absolute CAL Brier advantage over the already stronger unsplit baseline under perfect per-example expert selection, even before paying router/Cell/training overhead.

**Structural diagnostic:** The feature-geometry anchor assignment indicates **one of four fold expert orderings should be flipped in each seed**; output matching indicates **two of four**. A fold-reference permutation is indeed nontrivial, but **correcting identity alone is insufficient for demonstrated useful specialization**. All numbers are descriptive on a tiny, exposed training/calibration study. They cannot show significance, model superiority, generalization or a causal value of neural Cell division.

## Verification, physical costs and limitations

Two separately launched Linux processes re-trained the nine V17 gates; **9/9 actual safetensors digests** and all **2,496 CAL plus unscored prediction rows** repeated exactly. The separate NumPy/safetensors reviewer imports neither Torch nor producer, verifies **58 original V15 + 15 V16 + 9 V17 = 82 physical tensor bundles**, fold-specific normalizers/routes, fixed source SHA, training target hashes, logistic forward, 13 output profiles, post-label CAL-only oracle, and old-TRAIN/selection rules. Its maximum absolute probability discrepancy was **`9.485461993641309e-08`**, zero top-class flips. It does not recompute gradients or authenticate model publishers, hosts or label issuers.

**Four-generation tests:** V14 + V15 + V16 + V17 **128/128 PASS** in normal Python and **128/128 PASS** under `python -O`, with exact original files provisioned; **zero skips**. V17 contains deterministic mechanic, identity/no-authority, byte tamper and rehashed wrong-tensor, fold-target, route, calibration, blind-output and false future-claim negatives.

Metered separately executed V17-only whole-child (imports + 9 small SGD gates + readback/persistence, excludes V14/V15/V16 fitting, original pretrained Encoder and separate reviewer):

| Repetition | CPU user + system | Wall | Peak Linux `wait4` RSS |
| --- | ---: | ---: | ---: |
| A | 4.1021 s | 4.1042 s | 324,532 KiB |
| B | 3.6307 s | 3.6345 s | 324,296 KiB |

No per-arm CPU/memory or fair lifecycle compute ranking, OS power-loss/recovery, device energy, GPU throughput, p95/p99 or real 64/256/1024/4096 Cell production performance is claimed. Neither independent old-task retention nor true time-progressive future NDU utility was measured. The script never changes a production selected model, original signed effect owner or any capacity authorization.

| Candidate | Future utility gain | Independent negative transfer | Per-arm peak RSS | p99 | 4096-Cell throughput | Research outcome / no-change reference |
| --- | --- | --- | --- | --- | --- | --- |
| V16 extra-trained unsplit | Not measured | Not measured | Not measured | Not measured | Not measured | Retained reference, NOT deployed A0 |
| V17 unaligned OOF | Not measured | Not measured | Not measured | Not measured | Not measured | Rejected on retrospective CAL |
| V17 geometry-aligned OOF | Not measured | Not measured | Not measured | Not measured | Not measured | Rejected on retrospective CAL |
| V17 logit-reference aligned | Not measured | Not measured | Not measured | Not measured | Not measured | Rejected; reference-dependent, not independent OOF |

## Reproduction (private original data; no direct model/label upload)

```bash
cd qualification/stem-cell-v1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export HEPTA_V14_ORIGINAL_ZIP=/private/original-hepta-public-pretrained-38546717991.zip
python stem_counterfactual_split_v14.py prepare --archive "$HEPTA_V14_ORIGINAL_ZIP" --out /private/v17-input --labels-out /private/v17-temporary-held-labels.json
rm /private/v17-temporary-held-labels.json
python stem_stable_router_v15.py --inputs /private/v17-input --output /private/v17-v15
python stem_specialization_v16.py --inputs /private/v17-input --v15 /private/v17-v15 --output /private/v17-v16
python stem_identity_alignment_v17.py --inputs /private/v17-input --v15 /private/v17-v15 --v16 /private/v17-v16 --output /private/v17-candidates
python stem_identity_alignment_v17_review.py --inputs /private/v17-input --v15 /private/v17-v15 --v16 /private/v17-v16 --v17 /private/v17-candidates --out /private/v17-numpy-review.json
export HEPTA_V16_INPUTS=/private/v17-input HEPTA_V16_V15=/private/v17-v15
export HEPTA_V17_INPUTS=/private/v17-input HEPTA_V17_V15=/private/v17-v15 HEPTA_V17_V16=/private/v17-v16
python -m unittest -q test_stem_counterfactual_split_v14 test_stem_stable_router_v15 test_stem_specialization_v16 test_stem_identity_alignment_v17
python -O -m unittest -q test_stem_counterfactual_split_v14 test_stem_stable_router_v15 test_stem_specialization_v16 test_stem_identity_alignment_v17
```

The public Git branch contains **only executable research source, tests, sanitized aggregate JSON and this runbook**. No original question/article text, model weights, raw embeddings, per-case probabilities, routes or label-bearing data are committed. GitHub scoped CI and architecture+global security CI require **exact new HEAD completed receipts**. Research declaration alone is not a CI pass.

**Final scientific disposition: DO NOT PROMOTE V17.** Next scientific obstacle: obtain a task distribution with genuinely separable skills plus untouched source-family/time windows under independent outcome observation. Compare against strong no-change/reuse/unsplit before any automatic CellSplit. Keep `DENY_ALL`.
