# P2 matched lightweight Head — research only

**HOLD_NO_GO / DENY_ALL / SHADOW_ONLY**. This is a stacked source-only experiment on PR #2579's immutable research base; it does not change selected Neuron weights, model loading, inference Worker, CAS/CNS, NDU, FinalUse, or Cell Split. No model weights or publisher human labels are included.

## Why a new experiment

The original Laya native decision head, tuned Laya native head, OpenJev native decision head and an Ettin freshly fitted Head have different parameter-training interventions. Their original native decision scores cannot establish a *same-Head-training-budget* scientific winner. Each model must instead supply a frozen original Encoder feature bank for the **same complete evidence/question/ordered-options panel**; a model-specific read-only fixed feature hash projection brings differing encoder widths to 128 features, then a common 128 -> 32 sigmoid gate -> 1 binary logit Head uses **exactly 4,161 trainable parameters** and **40 full-batch SGD updates at LR 0.1**.

The projection has **zero trainable parameters** but is lossy. Both projection work (`N × D` additions/multiplications, scratch bytes and index bytes) and the expensive original Encoder forward must be charged. Training only matches Head trainable bytes/steps; **it does not match Encoder FLOPs, context quality, pretraining budget, tokenizer input length, optimizer RAM or end-to-end lifecycle cost.** Neither an equal Head budget nor a consistent simulated receipt qualifies physical model parity.

## Data custody and admitted inputs

`matched_head.validate_bank` requires a complete ordered source-first panel, a versioned frozen feature-bank schema, exact candidate repo+full revision, per-source/per-input SHA, complete fit/cal/test case IDs, fixed float32 widths, true declared original physical forward/source-byte audit (still self-report until independent issuer verification), no raw text or target labels and no production authority. It rejects unknown fields, duplicate/reordered/oversized/nonfinite features, source leakage and unmatched model identity. 

`matched_head.validate_fit` admits only **original FIT** labels. Neither CAL nor TEST labels may appear in training inputs. All Heads train using identical train rows and Head budget, each with its own fixed source-blind feature projection. The code returns private actual initial/trained parameter tensors and **raw uncalibrated CAL/TEST logits**, without using their labels. Do not upload tensors, raw features, per-case logits or hidden labels in GitHub workflow artifacts.

`matched_head_review` reimplements the 128D hashing projection and all **40 gradient updates independently in NumPy**, checks every tensor, complete weight hash, exact cost and individual untouched CAL/TEST logits; the reviewer must run outside the producer process for original study acceptance. Current tests exercise these separate math implementations in one local process only. The original held-label owner, calibration selection and longitudinal independent utility evaluator remain a further separate dependency.

No newly produced real 400M/421M frozen features or original-human binary accuracy exist in this P2 slice; all tests use tiny generated **synthetic** features and synthetic labels and certify numerical wiring only. No selection or promotion is possible even with a high synthetic score.

## Local verification

```bash
cd qualification/stem-replacement-p0
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  python -m unittest -q test_matched_head
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  python -O -m unittest -q test_matched_head
```

Research validation: 14/14 ordinary, 14/14 optimized; preceding P0/P1 source and snapshot tests plus P2 total 93 in each mode. Exact branch native hosted CI, actual pretrained features, independently authenticated source, future/OOD/negative transfer, real effect-free read-only benchmarks and full policy/Control/FinalUse gates remain unverified until separately observed terminal-success on each exact commit.

## P2.1 frozen Head initialization and honest equal-seed qualification

A source-only numerical investigation found a **real false-positive** in the first
independent replay: a producer could override the registered seed 41 with 42 or 99,
execute all forty genuine Torch SGD steps and self-consistently recompute every
reported tensor/prediction; the NumPy reviewer still returned HOLD_NO_GO with a
"pass" numerical replay. It had trusted producer-supplied *initial weights*.
The previous Torch-default initial tensors thus were **not a frozen independent
same-seed oracle**. This protocol explicitly supersedes those source-only fixture
initializations and does not carry any past score forward.

P2.1 defines model-independent **PCG64 uniform FP32 initialization**, in the fixed
shape/order [32x128, 32, 1x32, 1] using fan-in bounds for each layer. Both the
producer and independent NumPy reviewer implement the initializer separately.
The reviewer checks every original initial tensor byte, an explicit independent
initial-tensor SHA256, the exact registered panel seed, Head model identity,
original weights/reference identifiers, learning rate, dimensional profile,
non-authorizing authority flags, and complete receipt fields *before* replaying
all forty 40-step gradients. The trainer denies any seed override other than
that in the frozen panel. Source-only golden SHA256 for seed 41 is
`72236efb02d5da0b23ded8442bb2f68a7d2768ee53b1bb1ba089a0c8dc97f16f`;
seed 47 is `b5787d214c277443daf6adb2d7c5aa2e13901927b561ad62a9c44d6206fb36a7`.
The version marker is `hepta.stem.head-init.pcg64-f32.v2`.

The initial-tensor audit disallows cherry-picked or forged starting weights
*even if those forged weights were then used in a completely honest 40-step
Torch fit*. It does not add trusted publisher signatures, hidden-label custody,
physical pretrained checkpoints, equal compute or future-task gains. Matching
Head parameter budget and seed is necessary but not sufficient for model selection.

Verification (local Torch CPU, NumPy; **synthetic** inputs only): twenty P2
unit tests (normal and optimized) plus the preserved P0 gate suite; the new
cases cover seed-override denial, real-SGD forged initialization, wrong seed
and cost/identity spoofing, two real frozen-model-family Head initial tensors
and a fixed known initial tensor oracle. Hosted SHA-specific CI and original
pretrained model experiments remain separate, unresolved evidence gates.
