# Genuine frozen No-Change counterfactual (research-only / DENY_ALL)

## Finding and precise historical interpretation

The inherited four-arm trials intentionally train `no_change` for **two** phases:
`old_train` stage 1, followed by `old_train + new_train` stage 2. That arm does
not *split*, but its single parent Head **continues changing**. It cannot serve
as an unchanged deployed model counterfactual and must never be passed to NDU as
one. It remains a useful **unsplit continued-update** comparison. This new
additive experiment does **not** rename or rewrite old results, model weights,
source digests, wire protocols or tests.

A separately named `frozen_stage1_no_second_phase_learning` control uses the
exact saved FP32 stage-1 parent from the **same** already-trained original panel
and compares identical samples under the source's original labels. It verifies
that all four original training arms saved bit-identical stage-1 parents.
Stage 2 performs **zero Head training, zero optimizer steps and zero Router work**
for the frozen control. A real CPU PyTorch operation computes its holdout
predictions, then scores are formed after their digest is bound. An independently
implemented stdlib-only reviewer (no Torch, NumPy, trainer or new producer import)
rechecks the original soft, posthoc Top-1 and hard-trained report lineages,
original stage-1 tensor bytes, selected source identity, every posterior,
retrospective Brier/accuracy/NLL and measured-count conservation.

The original stage-1 execution and source provenance are **not independently
attested**; only its exact saved bytes are reused. This is a new comparison,
not independent new training, and cannot be relabelled as a second pretrained
model forward or a completely fresh no-change production deployment.

## Correct controls and denominator

| Arm | Stage 1 | Stage 2 | Sparse Top-1 | Interpretation |
| --- | --- | --- | --- | --- |
| `frozen_stage1_no_second_phase_learning` | inherited old-only training | **zero updates** | parent only | true frozen weights counterfactual |
| historical `no_change` | old-only | continued joint training | parent only | **unsplit continued update** |
| `fixed_router` | old-only | continued joint training | yes | fixed expert division |
| `learned_router` | old-only | REINFORCE router + Head training | yes | learned expert division |
| `adaptive_split` | old-only | threshold-triggered REINFORCE router + Head training | only if triggered | train-time structural candidate |

Count the true frozen stage-1 model training expense **once in the shared
historical source**; new post-stage1 fit cost is zero. Its stored FP32 Head size
is a logical weight-payload count, **not** process RSS. Actual additional
CPU inference time is self-reported and the auditor checks finiteness, not host
authenticity. Frozen versus online-trained controls have very different
training budgets. Equal-input-size or per-row inference does not make total
computation, future utility, statistical multiplicity or amortization equal.
Do **not** insert a zero-work control into a matched total-compute experiment
without explicitly accounting for the extra spend by its competitors.

## Completed toy pilot (three fixed seeds; two independent synthetic labels)

`local-evidence/six-panels-descriptive.json` stores six separate completed
source/checksum-bound CPU FP32 inference and independent numeric replay records.
Values below are retrospective Brier (lower is better). F1/F2 in these
experiments are **toy test subsets**; they are not real future calendar windows.

| Rule / seed | Frozen F1 | Unsplit continuing F1 | Frozen F2 | Unsplit continuing F2 |
| --- | ---: | ---: | ---: | ---: |
| Stable 41 | 0.071633 | 0.057210 | 0.078297 | 0.057529 |
| Stable 47 | 0.082065 | 0.056889 | 0.095600 | 0.072171 |
| Stable 53 | 0.087460 | 0.065700 | 0.087694 | 0.062093 |
| Conditional 41 | 0.342400 | 0.309380 | 0.300644 | 0.272969 |
| Conditional 47 | 0.310948 | 0.283161 | 0.330217 | 0.317399 |
| Conditional 53 | 0.303209 | 0.304466 | 0.309866 | 0.272377 |

The continuing baseline is better in **11/12** toy slices; the frozen model is
slightly better in conditional seed 53 F1. This only illustrates why the two
controls answer *different* causal questions. No algorithmic superiority or
reliable uncertainty bounds follow from the six authored synthetic panels.

## CI / evidence and admission boundaries

Run the new test suite with pinned CPU torch and numpy from a repository root:

```sh
python -m unittest qualification.cell_meta_execution_af.physical_router_frozen_tests -v
```

New isolated workflow runs this suite and additionally reconstructs all six
synthetic source → soft four-arm training → posthoc Top-1 → hard-trained Top-1 →
true frozen Head → independent stdlib replay. Retain failed evidence and source
hashes. It never downloads model weights, reads private user data, creates a
new execution owner, changes original NDU evaluator, or issues Final-use.

The actual pinned Granite 97M job remains separately queued under the upstream
PRs; no real new pretrained effectiveness result is claimed here. A future
experiment can attach this candidate only after its **original** source
binding, independent pre-label predictions, actual chronological outcomes,
complete costs and target-host receipts pass established NDU and owner gates.

Always publish `production_admission=BLOCKED`, `authority_posture=DENY_ALL`,
`future_window_prospective=false`, `true_ood_verified=false`,
`total_compute_matched=false` and `independent_ndu_selection_authorized=false`.
Do not merge into main or authorize physical Cell Split on this evidence.
