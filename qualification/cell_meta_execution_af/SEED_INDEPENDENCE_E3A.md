# E3a: Do not count deterministic seed labels as independent learning evidence

**DRAFT · RESEARCH · DENY_ALL.** This is a narrow additive audit stacked
after the exact Granite+Frozen E3 convergence. It does not change the
original `physical_router_trial.py`, Torch weights, dataset, routing
rule, shared Encoder, NDU Selector, execution ownership, CNS, Codex or
selected production artifact.

## Discovered study-design problem

The original Granite experiment fixes one 224-row shared feature table
for three declared seed labels 41, 47 and 53. In its original
`TwoHeadBank`, both Head rows and Router parameters initialize with
`torch.zeros`. The subsequent two-stage SGD uses full-batch,
fixed-order inputs, with no dropout, random sampling or randomized
initialization in the tested path. `torch.manual_seed(seed)` alone
does not make those deterministic training paths independent.

**Therefore 3 seed labels do not establish 3 distinct learned outcomes.**
On the *local shim-based 32-row old-only CPU smoke*, the three seed
labels produced byte-identical learned FP32 weight SHA-256 and sealed
prediction SHA-256. That experiment does **not** certify actual
original four-arm code or real pretrained Granite target execution.

## New independently replayed census

The standalone stdlib-only `physical_router_seed_independence.py`
opens exactly the 41/47/53 report groups. It requires:

- Identical full training/retention/test cases, features, source groups,
  labels, chronology and source identity across seed labels, except the
  seed metadata itself. Rehashed but changed data is rejected.
- One exact common original Q24 feature-table digest from the original
  Granite bridge receipts. These local hashes are **not** original
  model-origin signatures.
- Both unchanged independent FP32 auditors: four-arm Head/Router
  numerical replay **and** true old-only frozen Parent replay, including
  identical old-training step budgets and explicit mismatched total work.
- Exact five-arm names, every trained weights digest and every sealed
  prediction digest, per-seed source/result identity, and mandatory
  `DENY_ALL` flags. No effective tool
  capability or selected model is ever returned.
- Duplicate signature groups for each of the five arms, not just a
  single digest shared across models.

The report distinguishes `nominal_trials=3` from actual unique
numerical profiles per arm. Identical profiles produce
`IDENTICAL_NUMERIC_REPLICATES`; variation produces
`NUMERIC_VARIATION_ONLY`. Both retain
`independent_outcome_samples_established=false` and
`statistical_winner_certified=false`: observing different weights
would still not establish independent task-family outcomes or causal
Meta Network benefit.

A seed collapse is a **valid negative experimental result**, not an
excuse to delete the tests or quietly relabel replicas. The original
Granite workflow will independently re-check every individual model
and frozen score before adding the seed census to the *retrospective,
non-promotable* summary.

## Verification and next research design

The isolated local CPython 3.13 + Torch 2.10 CPU **shim-backed**
test run passed seven seed-census/adversarial cases, including a
physical frozen-Parent check. This does not imply the exact original
Granite/Router/FP32 suite passed. GitHub source-head and prospective
base-merge CPU tests remain mandatory, as do original pinned
pretrained-Encoder forwards and all global CI.

A later genuinely stochastic seed study requires a **separately
versioned, predeclared** initialization/sampling rule, paired initial
weights and identical training budgets across arms, with held-out
task families and independent outcome/label provenance. Never rewrite
the historical zero-initialization V1 or posthoc convert a seed label
into a statistical sample. Real target-host energy/CPU/RSS, original
signed CAS/State/CNS/Supervisor, Final-use and independent NDU selection
remain blocked.

**No effect execution, physical split, Codex fork, model selection,
main merge or release authority follows from this artifact.**
