# Five-arm shared-Granite Meta Router comparison (research / DENY_ALL)

This is an **additive, nonauthorizing** continuation of the frozen No-Change
candidate. It does not rename historical `no_change` (which continues training
while leaving the Cell unsplit), rewrite original four-arm reports, add a new
model loader or Selector, or mutate the Neuron/CNS/Worker execution path.

## Added physical execution in the existing Granite workflow

The inherited pinned research lane keeps one original 224-case AG News source
panel, one local Granite 97M R2 pretrained Encoder pass yielding Q24 features,
three fixed seeds (41/47/53), and the existing four experimental policies:

1. `no_change`: **unsplit, but stage-2 training continues**;
2. `fixed_router`: two expert Head slots, fixed sparse Top-1 policy;
3. `learned_router`: sparse Top-1 with train-label-only stochastic Router updates;
4. `adaptive_split`: optional split based solely on the train-window trigger.

After complete original source/feature/soft/posthoc/hard training and numeric
review per seed, the same source panel and **immutable stage-1 parent weights**
are passed to the already independently implemented `physical_router_frozen_baseline`
(from PR #2175) and `physical_router_frozen_review`. That fifth control does
**zero stage-2 optimizer steps and zero router training**; it is not a second
Encoder load and does not add a fourth seed. A new stdlib-only
`physical_router_fivearm_review` replays all five rows and binds their score,
cost, exact saved model bytes, source and evidence identities.

The workflow now retains each seed's frozen report, original-v-frozen reviewer
receipt and five-arm descriptive report separately from the historical records.
Before publishing, it asserts all three seed trial panels use identical real
source-group identities, labels, fixed projection features and original
model/tokenizer Scope. Repeating seeds does **not** produce new independent
sources, task families, or future calendar windows.

## Distinct scientific estimands

- `frozen_stage1_no_second_phase_learning` vs `unsplit_continued_update`
  isolates whether stage-2 learning helped, but their *training costs differ*.
- `unsplit_continued_update` vs `fixed_router`, `learned_router`, `adaptive_split`
  tests adding/specializing Cell Heads against continued single-Head training.
- `fixed_router` vs `adaptive_split` addresses the *actual* reason to permit
  structural evolution; its per-run/split/diagnostic/Router/migration cost must
  be measured, not declared equal.

The new five-arm reviewer reports each held-out slice's accuracy, Brier and
NLL, Brier differences against **both** baselines and separate:

- Common inherited stage-1 Head training rows (count once when comparing reuse);
- New stage-2 Head training rows and optimizer updates;
- Actual evaluation Head rows, Router training rows and diagnostic Head rows.

These counters are self-reported by original experiment/optimizer code and
numerically consistent with its saved route history; they are **not** an
independently signed process-level GPU/RSS/energy/migration/Encoder lifecycle
cost, and they do **not** establish total-compute parity. Existing original
physical Encoder execution is separately measured and its publisher identity
is not independently signed in this research lane.

## How to exercise without a pretrained model

From the repository root with CPU Torch and NumPy installed:

```bash
python -m unittest qualification.cell_meta_execution_af.physical_router_fivearm_tests -v
```

The tests perform genuine small CPU Torch fits and a separate independent
standard-library numeric replay, but only on explicitly **synthetic** data.
Both the old four-arm results and this fifth stage-1 control are unchanged
when a different algorithm is proposed; no selector, promotion or effect
operation is called.

## Evidence and hard blockers

The original AG News panel is a **retrospective cross-sectional** public sample.
Its `future_1` / `future_2` slots are not actual future observations; the `ood`
slot is same-source calibration material, **not validated OOD**. Three training
seeds are correlated repetitions on the *same* selected source rows.

The five-arm report always sets:

```text
retrospective_not_prospective = true
same_source_calibration_not_ood = true
training_budget_unequal_across_five_arms = true
complete_lifecycle_compute_matched = false
statistical_winner_certified = false
ndu_selection_authorized = false
original_worker_model_origin_signed = false
physical_cell_split_permitted = false
production_admission = BLOCKED
authority_posture = DENY_ALL
```

A positive retrospective slice must not select a Stem/Head, authorize Cell
Split, bypass the independently owned Final-use/CNS/Supervisor/Artifact CAS
checks, or claim a small device reaches a larger model's capabilities.
Current exact-head source/merge CI, real model forward artifacts, future
independent outcomes and complete lifecycle costs are still required.
