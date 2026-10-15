# Physical Top-1 MoE falsification: unchanged frozen Head weights (research only)

**Scientific status:** `DRAFT`, `DENY_ALL`, `production_admission=BLOCKED`. This
candidate stacks on Granite research PR #2110, its original soft-router PR #2090,
and A–F structural evidence PR #1796. It does not create a new learning owner,
NDU decision, CellSplit executor, model loader, selected artifact, Final-use
issuer, CNS cutover, Worker RPC, or production route.

## Why this is necessary

The original `physical_router_trial.py` physically computes **both** Head outputs
when `split_proposed=true`. The learned router then forms a soft mixture.
A bank of many logical Cells with soft-mixed Heads is **not** a sparse MoE proof;
its active-Head arithmetic is approximately proportional to the number of
Heads, despite unused logical Cell identities.

This increment tests the missing counterfactual without changing the original
SGD fit or its evaluation:

1. Load and independently replay the exact **four-arm soft-fit** source report,
   which includes final FP32 tensor bytes, routing policy, prediction seals and
   all old/new/train/future data identities. Invalid original material blocks
   before a Top-1 call.
2. Freeze those same weights. For each evaluation row, apply the existing
   fixed-sign route or learned gate sign. Partition inputs into selected Head 0
   and selected Head 1. Execute **only** the selected Head using a batched CPU
   `torch.mv` per occupied expert. Do not evaluate the other Head, even to
   construct a soft blend.
3. Meter active Head rows, router rows, actual nonempty Head batch matmuls,
   and observed CPU process time. This is observed *research code execution*;
   it is not independently signed Worker counters, FLOPs, energy, wall-time p99,
   or proof of deployment speedup. Pretrained Stem execution costs are unchanged
   and not made free by Top-1 routing.
4. Seal all Top-1 predictions and their row/route identities before the
   `score()` function computes per-slice accuracy/Brier/NLL. This is an offline
   retrospective procedure on a dataset with known public labels — **not** an
   independently witnessed pre-label commitment.
5. A second completely stdlib-only numeric reviewer (no Torch, no import of
   Top-1 producer or scorer) recomputes the source bindings, frozen FP32 weight
   bytes, deterministic route for every row, one selected Head's logistic output,
   original train budget, prediction seal, per-head count, router count, actual
   nonempty batch count and every descriptive metric. It refuses forged
   bookkeeping, relabelled authority, missing/extra work or malformed input.

## What is actually compared

| Arm | Original soft Head evaluations per row | New Top-1 Head evaluations per row | Router evaluations |
|---|---:|---:|---|
| `no_change` | 1 | 1 | none |
| `fixed_router` | 2 | 1 | feature sign only |
| `learned_router` | 2 | 1 | one gate vector dot-product |
| `adaptive_split` | 1 if unsplit; otherwise 2 | 1 | none if unsplit; gate if split |

Hard Top-1 **need not preserve** the soft-mix model's quality. The original soft
weights were optimized for two-Head mixtures, not for hard expert selection.
A lower Head row count is not a net win if routing, gathering, recovery, or
quality degradation outweigh it. In particular, a fixed/oracle feature-sign
router can retain an advantage that is not caused by learned Meta Network
structure. Record negative deltas exactly; no tuning on test labels.

## How to execute

From a trusted root with exact source checkout and Torch CPU runtime:

```sh
PYTHONPATH=. OMP_NUM_THREADS=1 python3 -m unittest discover -v \
  -s qualification/cell_meta_execution_af -p 'physical_router_top1_tests.py'

python3 qualification/cell_meta_execution_af/physical_router_top1.py \
  --panel /path/to/41-trial-panel.json \
  --soft-report /path/to/41-trial-report.json \
  --out /path/to/41-top1-report.json

python3 qualification/cell_meta_execution_af/physical_router_top1_review.py \
  --panel /path/to/41-trial-panel.json \
  --soft-report /path/to/41-trial-report.json \
  --top1-report /path/to/41-top1-report.json
```

The existing `hepta-cell-meta-granite-real.yml` physical job now executes this
ablation for the three actual Granite-seeded Head fits, **only after** their
original model, source, training and independent numerical gates succeed.
The first-stage offline job exercises adversarial tests without model downloads.
Missing real model weights or actual model failure is a research failure, never
replaced by a synthetic success in that physical job.

## Nonclaims and the next strict science gates

`future_1/future_2` in the Granite study remain retrospective *AG News* test
subsets, and `ood` is an in-family calibration placeholder. No genuine
prospective timestamps, natural task-family OOD, independent raw labels, true
Hepta external tasks, cryptographic model/Worker custody, original-owner signed
Final-use, target-host 64..4096 end-to-end p99, CAS/WAL/recovery, NDU utility,
or independently validated stochastic confidence intervals exist in this
research slice.

A future fairness experiment must independently compare *hard-trained* Top-1
experts, soft-mix experts, fixed oracle/sign, learned policy, continued unsplit
Head, and dynamic split at equal **total** training/search/inference/recovery
budgets, including active router/gather and shared-Encoder overhead. Train-only
routing selection must be frozen before future labels, and all rejected
candidate attempts remain in the denominator. Only external independent future
outcomes, absence of negative transfer, matched lifecycle costs and existing
original authority owners can justify a separate production promotion proposal.

This new diagnostic has no authority and may not merge, select an artifact or
activate any physical CellSplit merely from better Top-1 retrospective scores.
