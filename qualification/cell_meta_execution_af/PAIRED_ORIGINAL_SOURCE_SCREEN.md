# Three-seed original-source paired contrast — research only / DENY_ALL

## Objective

The existing [five-arm Granite study](FIVE_ARM_GRANITE_HANDOFF.md) trains
separate Head/Router weights under seeds 41, 47 and 53 on **the same** pinned
AG News material. Treating three seeds × 32 same-source examples as 96 independent
future tasks would manufacture evidence. The new stdlib-only paired screen
counts **32 source groups**, not 96, for each retrospective test slice. It
provides a diagnostic comparison; it does not optimize a model or decide whether
a Cell should divide.

## Exact inputs and procedure

Consume the existing six create-only artifacts for each of seeds `41/47/53`:
`trial-panel`, `trial-report`, `top1-report`, `hard-train-report`,
`frozen-report`, and `fivearm-report` under the same recorded source/Scope.
Before any summary, call existing **independent** soft / posthoc / hard / frozen
numeric auditors through the canonical five-arm reviewer. Reject a forged
five-arm score even if the claimant updates its own hash. Every original
source group, split, feature, label, and order must be **byte-semantic identical**
across the three seeds; only the registered training-seed field may differ.
Never substitute a neighboring data partition, edited label, or new Encoder
for a fixed experimental row.

For `future_1`, `future_2` (both retrospective public test splits), compute
original-case per-seed Brier differences:

* `adaptive_split - fixed_router`
* `adaptive_split - unsplit_continued_update`
* `adaptive_split - frozen_stage1_no_second_phase_learning`

Average each original-case delta across the three correlated **training seeds
before** averaging original source cases. Keep the individual seed-conditional
means visible. A fixed SHA-256 counter sampler produces 1,024 deterministic
within-panel original-case bootstrap means; the 0.05/(3 contrasts × 2 test
slices) multiplicity allocation is disclosed in the report, but its displayed
endpoints are **not independent-family, prospective, calibrated frequentist
confidence bounds**. Single-dataset article source groups can share context,
annotation biases, and pretrained overlaps; source-family independence has
not been proven. Never promote on the sign of either endpoint.

The screen also reports exactly one shared 224-row source inventory for the
real Granite job. This is only a canonical source-row count, **not** signed
proof that the Worker physically executed 224 Encoder forwards or that the
observations were collected in the future. The source is retrospective and
readily visible during experiment development. It remains separate from any
production no-change or original signed FinalUse receipt.

## Execute

After successful original model execution and **all** five-arm reviewers:

```sh
python -m unittest -v \
  qualification.cell_meta_execution_af.physical_router_paired_screen_tests
python qualification/cell_meta_execution_af/physical_router_paired_screen.py \
  --bundle-dir /path/to/pinned-shared-granite-reports \
  --out /path/to/new/paired-original-source-screen.json
```

The existing Granite workflow invokes the screen **after** its three seed runs.
It retains the exact output alongside the five-arm receipts; no new HF or Torch
model load is introduced. Strictly refuse missing seed, changed task identity,
changed original case ordering, tampered prediction, altered Head/Router weight,
false NDU/CI status, non-finite value, non-file input or existing output path.

## Scientific and production interpretation

All successful reports set
`prospective_calendar_outcome_verified=false`,
`independent_original_source_family_count_authenticated=false`,
`valid_independent_effect_confidence_bound=false`,
`matched_complete_lifecycle_compute=false`, `selection_approved=false`,
`ndu_accepted=false`, `physical_cell_split_permitted=false`,
`production_admission=BLOCKED`, `authority_posture=DENY_ALL`.

The current dynamic split may remain worse than fixed Top-1. The next legitimate
causal test must introduce a separately pre-registered, independent source-family
**and** chronological future outcome panel, with total training/search/Encoder
costs and signed original Worker/CAS/CNS/FinalUse paths. Changing a label or
claiming an additional seed does not create that experiment.
