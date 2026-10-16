# V14: original-feature Cell split, capacity control and route counterfactuals

2026-10-15 (America/New_York). **RESEARCH / SHADOW_ONLY / DENY_ALL.** Additive continuation of Draft #2364, inspected parent `6df9ec75b1db31e0446ad024c87288e444b18137`. No original V5-V13 source, Rust owner, model custody, NDU, FinalUse, main or production route is modified.

## Why this experiment, not another Cell-count demonstration

The separate real Granite five-arm archive (PR #2344, source `a14141be69c60cb5af36dd5fc706960b3f2bfcf9`, run `38728188125`) reports no adaptive split at any of three seeds. Adaptive and continued-unsplit outcomes coincide. That is a useful no-growth decision, but it cannot identify the efficacy of an actual split. Its redacted archive contains no original tensors for a fresh local counterfactual. Do not relabel this V14 mmBERT study as a Granite rerun or mix their samples.

V14 physically trains split candidates in all three seeds, compares them with frozen, continued and inherited wider unsplit controls, and evaluates the SAME learned split tensors under original, shuffled and swapped routes. It does not force a split to win the calibration selector.

## Original material, not synthetic feature/label substitution

- Original GitHub run: `38546717991`; artifact: `11890616195`, `hepta-public-pretrained-38546717991`.
- Original producer source: `4133d6ac5bd3f8d4200c56fffb09e6aba004a084`.
- Full original ZIP: 1,398,480 bytes; SHA256 `0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7`. Library bytes matched the original GitHub artifact digest and size.
- `jhu-clsp/mmBERT-small`, immutable revision `abc32620dd4f6ab06f5fbe905dc25f310618e09f`.
- Original AG News dataset SHA256 `50335a2214756c7a9e09fee9ac9ed27ab855ea98635bb0fab0998144165ffb2c`.
- Saved FP32 128 x 384 real Encoder tensor file SHA256 `e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490`.
- Exactly 64 TRAIN, 32 calibration and 32 previously exposed held records, four original publisher classes. All seeds reuse these records. They are NOT 96 independent held cases, a new source-family census or actual future time windows.

Preparation checks original scoped text input digests against the archived feature manifest, then writes label-free held inputs separately from original held labels. The preparer sees labels; this is process separation, not independent label custody or OS-enforced isolation. No raw text, labels, features, per-case held probabilities or pretrained/model tensors are committed. No new pretrained Encoder forward was performed. Byte identity does not authenticate a publisher signature or deployed model owner.

## Frozen protocol and physical budgets

Each seed (41, 47, 53) trains a fresh linear 384-to-4 parent on the first 32 TRAIN records for 80 SGD updates. This is an artificial retrospective training schedule, not a deployed A0 checkpoint or temporal environment change. Three continuations use the same 80 batches of 16 examples from all 64 TRAIN records, learning rate 0.1. All hyperparameters were fixed for the first V14 campaign and left unchanged after viewing its held results.

| Arm | Trainable scalars in second phase | Frozen routing scalars | Resident scalars | Second-phase updates |
| --- | ---: | ---: | ---: | ---: |
| Frozen parent | 0 | 0 | 1540 | 0 |
| Continued parent | 1540 | 0 | 1540 | 80 |
| Wider inherited unsplit | 3878 | 0 | 3878 | 80 |
| Inherited two-Head split | 3080 | 768 | 3848 | 80 |

The wider arm is parent plus a rank-6 Tanh residual whose output is initially zero. The split inherits two distinct parent weight copies and a label-free two-centroid TRAIN-only router. Both reproduce parent outputs before training within the declared numerical tolerance. No padded dummy weights are used. Wider and split resident capacities differ by 30 scalars (about 0.78% of split storage); trainable capacity, gradient bytes and active computation are NOT exactly matched. SGD has no momentum/optimizer-state tensors; gradient storage is accounted separately.

The train partition uses 43/21 original rows in the two routes. Each selected-row split minibatch computes only its selected Head: 1,280 Head-row operations across 80 updates, not 2,560 dense two-Head rows. This is a counted operator property, not measured total FLOP, latency, energy or 4096-Cell throughput savings.

All four models per seed are saved and frozen before held scoring. There are 12 actual models and 960 SGD updates per complete campaign (including three stage-1 parents). The descriptive selector uses calibration Brier plus a fixed small parameter charge, a 0.01 improvement margin, and an old TRAIN-fit regression bound. A growing candidate must also beat continuation by the margin. The old-fit check is NOT independent old-task retention. No held label is passed to fitting or selection. Selection returns a research candidate only.

## Actually executed results: specialization not established

Correct classifications out of the SAME 32 previously exposed original held cases:

| Profile | Seed 41 | Seed 47 | Seed 53 |
| --- | ---: | ---: | ---: |
| Frozen fresh stage-1 parent | 7 | 8 | 8 |
| Continued unsplit | 21 | 15 | 16 |
| Wider inherited unsplit | 8 | 20 | 15 |
| Split with original learned-feature route | 17 | 25 | 17 |
| Same split weights, shuffled routes | 16 | 26 | 18 |
| Same split weights, swapped routes | 20 | 25 | 23 |

Calibration selects **continued / split / continued**, respectively. Swapping expert routes is not worse than the intended route on any seed; on two seeds it is better. This does not identify effective specialization. Shuffled routes are a deterministic held-batch permutation preserving route counts, not a deployable causal routing policy. Swapping changes only which frozen Head runs; neither lesion is retrained or promoted.

The raw-feature fixed SGD schedule also produces saturated weak frozen baselines and large between-seed changes. This is a poor basis for claiming an optimal split, overall architecture superiority or a stable useful learning policy. No post-held learning-rate search or replacement of unfavorable results was performed. The next study needs training-only optimization stability checks, meaningful route/skill objectives and untouched source-disjoint evaluation; it must charge that search.

## Execution and independent verification

Two separate original-feature training processes each completed all 12 saved models and 960 updates. Their 12 parameter digests, all 576 held-profile probability rows and three calibration selections match exactly. CPU timing differs normally. The committed result records both prediction-file digests and fit-loop CPU values; the JSON files differ because they include timings.

A separately invoked NumPy/safetensors reviewer imports neither Torch nor the producer. It verifies the actual producer file bytes, immutable archive/input identity, all 12 physical tensor inventories/digests, calibration and old-fit scores, selection, routes, and all 18 profiles. Maximum probability deviation is **9.56541793784016e-06**, within 5e-5, with zero top-class flips. This reviewer independently recomputes forwards and scores; it does NOT re-execute gradients, verify an external host signature or certify statistical efficacy.

**30/30 local tests PASS normally; 30/30 PASS under `python -O`; zero skips with the exact archive mounted.** The suite includes 16 mechanism tests with disclosed synthetic fixtures and 14 original-archive integration/tamper cases. Python compilation, YAML parse and every workflow shell block's `bash -n` passed. Local runtime: Python 3.13.5, Torch 2.10.0+cpu, NumPy 2.3.5, safetensors 0.7.0. Local analysis CPU is not the user's dot or a production acceptance host.

New CI is path-filtered, exact-source checked and read-only. PR runs execute the mechanism suite; push/dispatch additionally retrieve the exact original artifact, train and independently replay actual original features, then upload ONLY sanitized aggregate review. Missing archive or hash mismatch fails, never synthesizes replacements. Hosted exact-new-SHA, Architecture and global blocking checks are not preclaimed green.

## Reproduce in a new private output location

```bash
cd qualification/stem-cell-v1
export HEPTA_V14_ORIGINAL_ZIP=/private/hepta-public-pretrained-38546717991.zip
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python -m unittest -v test_stem_counterfactual_split_v14
python -O -m unittest -v test_stem_counterfactual_split_v14
python stem_counterfactual_split_v14.py prepare \
  --archive "$HEPTA_V14_ORIGINAL_ZIP" --out /private/v14-input \
  --labels-out /private/v14-held-labels.json
python stem_counterfactual_split_v14.py train \
  --inputs /private/v14-input --out /private/v14-candidates
python stem_counterfactual_split_v14_review.py \
  --archive "$HEPTA_V14_ORIGINAL_ZIP" --inputs /private/v14-input \
  --candidates /private/v14-candidates --output /private/v14-review.json
```

Source: `stem_counterfactual_split_v14.py`; independent replay: `stem_counterfactual_split_v14_review.py`; tests: `test_stem_counterfactual_split_v14.py`; sanitized actual readout: `STEM_V14_COUNTERFACTUAL_SPLIT_RESULT_20261015.json`.

**No promotion:** no generalized agent emergence, giant-model equivalence, real NDU gain, true future retention, exact cost equality, original Granite retention repair, new pretrained model choice, native Q24 parity, original CAS/CNS/FinalUse custody, production lifecycle/recovery or 64-4096 Cell device qualification. Keep Draft; main and every production owner remain unchanged.
