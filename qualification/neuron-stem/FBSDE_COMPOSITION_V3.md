# Shared learned composition after the physical Encoder result

This optional profile continues #1550 from
`9bc25e567f446ec55ff367f2a9e1e3b5004c5838`. It retains both question profiles,
all earlier controls, the nonlinear coupled study, the canonical acceptance
reviewer, original owners, and unchanged CPU limits. It does not reinterpret
Boolean composition as the general continuous nonlinear NDU/FBSDE problem.

## What the original hosted experiment now shows

Run 38145506994 completed all five jobs, including both real mmBERT profiles,
exact source/merge studies and learned coupled fields. Original Encoder artifacts
11705053694 (V1) and 11705018573 (V2) have archive SHA256 values
`ee99c1d20fee4e5237cff89b016e42e34c5e5722a054e08983bc6a08d8784e62` and
`6596220ee32e0765e8b4f5747962fefb50a3a8426137b62283aee6e62733a590`.
Both source records name exactly the above parent. Independent arithmetic replay
recovers all 192 answers per arm. V2 root results are:

| Method | Decoded accuracy | Binary Brier |
| --- | ---: | ---: |
| Existing light Head | 0.6875 | 0.28655317 |
| Best fixed recurrence (one round) | 0.68229167 | 0.22988339 |
| Simple stop | 0.66145833 | 0.24430374 |
| Syntax-only prior | 0.83333333 | 0.12167867 |
| Full f=0 belief-tree BSDE | 1 | 0.00038093 |
| Cheap exact algebraic control | 1 | 0.00038093 |

V1 also has 192/192 correct for both exact methods. Their equality is expected
from the registered independent-leaf law, not a special BSDE advantage. The
pre-question conditioning limitation of V1 and shared-source dependence remain.
These simple generated formulas over four intents do not establish general
language reasoning. They motivate a compositional learned control, not a larger
probability tree or a claim that increased recurrence necessarily helps.

## An eight-parameter trainable Cell, not a hard-coded truth-table teacher

`independent_targets_composition_v3` retains the exact V2 public questions and
same semantic Head. For each of two public operator IDs, it learns four corner
probabilities w00,w01,w10,w11, initialized ALL at .5. A node with child predictions
a,b computes

    (1-a)(1-b)w00 + (1-a)b w01 + a(1-b)w10 + ab w11.

All nodes reuse the same eight scalars, with no new Encoder or per-depth tensor.
They receive only the original root training labels, never operator-table targets
or held-out labels. The 96-step AdamW schedule, learning rate .003, clipping and
training/prediction CPU ceilings are unchanged. Projection keeps parameters in
[1e-6,1-1e-6]. Operator syntax and read-once structure are explicit inductive
biases also present in the exact control. This is not learning latent syntax.

The root models all have the same AVAILABLE information; this compact model
chooses to consume semantic probabilities and syntax, not all raw features.
A frozen .5-table control uses the same trained semantic Head. Actual saved
float32 corner bytes and the frozen tensor identity are checked in the audit.
Torch batches same-syntax training rows. Runtime evaluates eight frozen numbers
without starting a Torch operation per internal node. Tree depth is maximum
causal operator depth; guard and fallback work are counted separately.

## Optional original-law decision check, not a calibrated confidence claim

The unchanged AND/OR probability maps are each 1-Lipschitz in each child on
[0,1]. If approximate child errors are E_l,E_r and the local original-map defect
is d, then the root error is at most min(1,E_l+E_r+d). This follows by the triangle
inequality, induction and the common terminal leaf values. It concerns the SAME
finite f=0 model as `belief_bsde`, not truth of the semantic probabilities.

The guarded arm computes that defect at every internal node. When the root
interval lies strictly on one side of .5 (plus a 1e-12 engineering cushion), it
keeps the learned output; otherwise it uses the cheapest exact formula, not an
unnecessary full tree. No future label is read to choose this fallback. The
formula checker and fallback are NOT free. The float bound is not interval
certified and does not cover a wrong conditional law or external answer error.

## Executed downstream replay, kept separate from fresh model execution

The new profile was executed on the original V2 physical feature artifact, SHA256
`19214e07bcc84d94694fc98e7920d8b404366efdbed0dc5a6b3e5b07cf8a7063`.
All 328 original IDs, raw vector batch hashes and the train-only normalizer were
rechecked. This is new actual downstream training/inference on measured real
features; it is NOT a new Encoder forward pass or an independent holdout.
The older results had already been inspected, so this is exploratory reuse.

The learned corners reduce training BCE from .69314730 to .28920352. Frozen,
learned and guarded composition score 44/192, 192/192 and 192/192 respectively.
The learned Brier is .12147294: perfect decisions here do NOT imply strong
calibration. All 192 guarded cases fall back, producing the cheap exact Brier
.00038093. No threshold is weakened to create accepted approximate decisions.

One final local batch measures adaptation-plus-inference CPU LOWER BOUNDS of
.635085308s (existing light Head), 1.715582686s (best-fixed), .213655193s (learned
composition), .206999089s (guarded composition), and .104228253s (cheap exact).
These component values include common semantic fitting but exclude fresh Encoder
load and other unallocated lifecycle phases. They are not stable speed claims;
the guarded/unrestricted timing ordering also illustrates small-batch variation.
The exact method remains the cost/calibration winner. Training eight parameters
has not justified replacing a known exact algorithm or the native owners.

## Verification and next evidence

The final local qualification subtree executes 229 model-free regressions and
34 actual Torch checks with no skips. The old nine V2 arms reproduce all
9 x 192 saved non-timing prediction fields exactly on the original real features.
The independent auditor imports neither learned model nor solver, recomputes
corner-byte commitments, learned probabilities, original-law decisions, fallback
counts and all inherited answer/budget checks. Historical source files are kept.

The existing physical workflow adds V3 as a separate job, preserving V1 and V2.
Its own final-source hosted outcome is required before a new physical execution
claim. No source-only test, shared-feature replay or perfect score on these reused
simple tasks supplies current no-change, unseen independent task families,
accepted-error guarantees, full lifecycle benefit or native final-use/recovery.
Keep Draft and production promotion disabled.
