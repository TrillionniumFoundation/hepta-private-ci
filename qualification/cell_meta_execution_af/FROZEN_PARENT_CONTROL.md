# E2f frozen-parent control for Cell/Meta physical-router trials

**Draft / Research DENY_ALL.** This additive comparator retains the original
A–F and physical-router V1 source, report schemas, CI and owners without editing
them. Nothing here trains real pretrained Stem weights, runs Codex tools, changes
CNS routes, invokes NDU Selector, or permits physical Cell Split.

## Defect in the historical comparison label

The V1 arm named `no_change` is **unsplit, not frozen**: its `train_arm` runs
24 old-task optimizer updates *and 24 more updates on combined old/new rows*.
The resulting scores are a valid **continuously trained, fixed-topology**
control, but cannot be called a frozen `no-change` reference in causal NDU
selection. Reusing the name to claim immutable baseline would be erroneous.

## New additional counterfactual

`physical_router_frozen_old.py` uses the same pinned toy panel,
`TwoHeadBank`, initial zero weights, FP32 Torch, SGD learning rate and old-task
step count; it physically trains **only** `old_train`, freezes the real weights,
then produces the four old-retention/future/OOD prediction panels. All future
predictions are sealed before reading labels for scores. It never takes a
new-task SGD step, never splits, and does not claim equal total compute.
The output schema is distinct: `hepta.cell-meta-frozen-old-parent.v1`.

`physical_router_frozen_old_audit.py` performs Torch-free numerical replay from
exact FP32 weight bytes, validates original panel identity, cohort case IDs,
metric recomputation, old-only sample accounting, absence of trained second
Head/router weights, and permanent DENY_ALL. The optional `--continued` input
must itself pass the existing independent V1 four-arm audit and is explicitly
classified as **not frozen**. Both numerical meters and source provenance are
still locally claimed; this is *not* independent evidence authentication.

## Run

```sh
python3 -m unittest qualification.cell_meta_execution_af.physical_router_frozen_old_tests -v
python3 qualification/cell_meta_execution_af/physical_router_frozen_old.py \
  --synthetic-rule conditional --seed 41 --report /tmp/hepta-frozen-41.json
python3 - <<'PY'
from pathlib import Path
from qualification.cell_meta_execution_af.physical_router_trial import canonical, synthetic_panel
Path('/tmp/hepta-frozen-panel-41.json').write_bytes(canonical(synthetic_panel(seed=41, rule='conditional')))
PY
python3 qualification/cell_meta_execution_af/physical_router_frozen_old_audit.py \
  --panel /tmp/hepta-frozen-panel-41.json --frozen /tmp/hepta-frozen-41.json
```

**Selection gates still blocked:** externally verified task source and labels,
precommitted actual deployment no-change model, real pretrained Stem weights,
future independent task families, matching *total* training/serving/evaluation
cost, original signed Owner operation receipts, holdout/revocation/negative
transfer, accepted NDU bounds, and target-host physical profiling. The frozen
old-only control also incurs less training than a continued-training arm: it
is a learning-control reference, **not** an equal-compute structural winner.
Do not automatically merge, deploy, promote, or use this report as a grant.
