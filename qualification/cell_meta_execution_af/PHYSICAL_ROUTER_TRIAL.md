# Cell split vs fixed MoE: real tiny-Head CPU research trial

**Scope:** research-only, `DENY_ALL`. This adds a *physical* Torch FP32
training/replay slice underneath the existing A–F **shadow conformance** PR #1796.
It does not replace `gate.py`, NDU, inference.control, Neuron, CNS, the original
Cell Split execution owner or Codex. No `main` or selected model is modified.

## What is actually implemented

- **Identical frozen feature rows and label inventory for four arms:** `no_change`,
  `fixed_router`, `learned_router`, `adaptive_split`.
- **Actual** float32 Torch tensors, BCE gradients, 48 optimizer steps per arm
  (24 old only, 24 old + new), matched input-row exposures, one shared input
  matrix, 2 physical Head slots and one router parameter slot for every arm.
  Distinct active Head, Router and training row counts are recorded; **total
  compute and latency are not matched**. There is no pretrained Encoder load.
- At split, clone the *trained* parent into its sibling, verify prediction parity
  before any second-stage update, and allow distinct gradients thereafter.
  `fixed_router` routes by the preregistered feature sign; `learned_router`
  trains a soft gate. `adaptive_split` only activates a new branch when the
  old-trained model's **training-only** new-vs-old Brier excess exceeds 0.08.
- Preserve 4 separate label-bearing evaluation cohorts in the immutable input
  (`old_retention`, `future_1`, `future_2`, `ood`). No evaluation label enters
  any gradient, threshold or routing decision. A label-free probability
  commitment is hashed **before** the local scorer opens evaluation labels.
- Export complete FP32 little-endian Head/Router bytes, complete per-row
  probabilities, weight/prediction digests and all outcome counts. The separate
  **stdlib-only** `physical_router_audit.py` recomputes final Head predictions,
  every score and internally claimed Head/Router forward-row meter; it does
  not import the trainer, Torch or the trainer's scorer.
- File reader requires strict cohort identities, no cross-cohort shared source
  group, chronological order, finite bounded features, binary labels, no extra
  critical fields, no duplicate JSON keys, size limits, regular files and no
  symlinks/FIFOs. Report write is create-only. These are **research
  integrity checks**, not independent original-source authentication.

## Exact local CPU diagnostic (PyTorch 2.10.0+cpu; 96 toy rows per cohort)

The two rules are explicitly generated **synthetic data**, not real Stem
representations, external observations or prospective windows. Three separately
fixed seeds were run. Percentages below are descriptive, uncorrected.

| Seed / toy rule | No-change future 1 / 2 accuracy | Fixed Router | Learned Router | Adaptive Split | Adaptive split? |
| --- | --- | --- | --- | --- | --- |
| 41 / stable | 96.88% / 98.96% | 96.88% / 98.96% | 96.88% / 98.96% | 96.88% / 98.96% | No |
| 41 / conditional | 56.25% / 53.13% | **76.04% / 76.04%** | 60.42% / 62.50% | 60.42% / 62.50% | Yes |
| 47 / stable | 98.96% / 92.71% | 96.88% / 92.71% | 96.88% / 92.71% | 98.96% / 92.71% | No |
| 47 / conditional | 59.38% / 54.17% | **70.83% / 70.83%** | 63.54% / 58.33% | 63.54% / 58.33% | Yes |
| 53 / stable | 94.79% / 98.96% | 93.75% / 98.96% | 93.75% / 98.96% | 94.79% / 98.96% | No |
| 53 / conditional | 55.21% / 66.67% | **67.71% / 80.21%** | 63.54% / 72.92% | 63.54% / 72.92% | Yes |

For the 96-row seeded panels, no-change and unsplit adaptive cases
execute **7,296** actual Head forward rows; always-split variants execute
**12,288** Head forward rows plus up to **4,992** learned Router forward rows.
Each arm performs 48 optimizer updates and 6,912 train-row exposures.
The fixed Router is strictly better on the two conditional heldouts for all
three seeds; this is an **actual negative result** for the adaptive superiority
hypothesis, not something to hide. When adaptive splits, its exact training
path is the same as always-learned Router; the experiment isolates the
train-only *split/no-split* decision, **not** a separately superior meta-learning
algorithm. Learning-rate and task design remain research choices, not tuned
using the evaluation cohorts.

A single CPU process executes arms sequentially, so per-arm CPU time is only
observational and order-biased. Neither energy, end-to-end RSS, full Decoder,
CNS, original Final-use nor 4,096 production Cell latency is measured here.
The 96 toy rows are not 96 statistically independent real-world episodes.

## Reproduce / independently replay

Python 3.11+ and CPU PyTorch are required only for the producer/tests;
`physical_router_audit.py` itself uses only the standard library.

```bash
python -m unittest qualification.cell_meta_execution_af.physical_router_trial_tests -v
python qualification/cell_meta_execution_af/physical_router_trial.py \
  --synthetic-rule conditional --seed 41 --out /tmp/hepta-router-41.json
python - <<'PY'
from pathlib import Path
from qualification.cell_meta_execution_af.physical_router_trial import synthetic_panel, canonical
Path('/tmp/hepta-router-41-input.json').write_bytes(canonical(synthetic_panel(seed=41, rule='conditional')))
PY
python qualification/cell_meta_execution_af/physical_router_audit.py \
  --panel /tmp/hepta-router-41-input.json --report /tmp/hepta-router-41.json
```

For external input, supply a complete `hepta.cell-meta-router-panel.v1`
JSON via `--input` with `source.kind=external_unverified` and
`source.rule=external`. No code invokes providers or downloads weights.
The audit checks raw bytes and numerical consistency **but cannot** verify
source licenses, real Encoder provenance, original label independence,
physical training counters, signed prelabel commitments or that a true
future window was unseen. A report alone is never a learning admission.

## Non-negotiable acceptance boundary

Every emitted result declares `independent_outcome_verified=false`,
`future_window_prospective=false`, `total_compute_matched=false`,
`statistical_winner_certified=false`, `ndu_selection_authorized=false`,
`production_admission=BLOCKED`, `authority_posture=DENY_ALL`.
The next scientific experiment must compare fixed/preallocated/adaptive routes
with genuinely source-disjoint *real* tasks, physically attested shared Stem
features, two protected future windows, external independent outcomes,
full training + inference + migration + search cost, old-task retention,
stronger fixed controls and a frozen no-change NDU baseline. The existing
A–F gate, selected Artifact CAS, signed Final-use and original-owner
physical Cell Split remain independently necessary.
