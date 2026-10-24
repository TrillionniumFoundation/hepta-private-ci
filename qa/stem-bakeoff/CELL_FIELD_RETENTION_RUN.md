# Optional retention control: actual-state execution and new-source admission

This additive module deploys the optional one-sided objective through the existing
`CellTrainingState.advance` implementation. It does not alter the published PFT
objective, controller, runner, May/June results, or the separately reviewed
`cell_field_retention.py` solver. There is no new empirical efficacy result here.

## Exact algorithm and limits

The controller uses **frozen-reference tangent MPC**, with the original full
optimizer state `theta/m/v`, current training context, and original no-control
trajectory. At step `k`, it measures
`z = (actual_state - original_reference_state[k]) / original_scales`, solves the
remaining original `A/E/C` problem, and applies only the first control. It does
not relinearize around the controlled trajectory. The numerical suffix optimum
is an optimum of the declared affine model, not of the actual nonlinear model.

For old-probe loss `L_old`, the new penalty is
`old_weight / 2 * max(L_old - anchor - tolerance, 0)^2`.
`anchor` must exactly equal the original warmup endpoint's old-probe loss. The
full old target path `anchor + tolerance - original_reference_old_loss` is built
once and sliced at every step. Resumption cannot reset this anchor. The current
target is the original reference-relative target throughout.

`Reference.action_matrix` already includes `dt` in `E`. A deployed physical
intervention is exactly `dt * B @ u`, added after the unchanged Adam update.
Moment values, step, sampler state and data contexts remain part of the actual
training state. Runtime magnitude guards reject an action or condition; they do
not clip controls or switch to a fallback objective.

The same wrapper supports `zero`, `legacy_full_quadratic`, and
`retention_hinge_suffix`. The first two call the original `fit_controller` and
`Controller.action`. The legacy old target remains `anchor - reference_old`,
with its original quadratic charge, even when the optional tolerance is positive.
Every completed arm reports explicitly named `legacy_quadratic` and
`optional_one_sided` diagnostic costs. Neither is a task-success metric.

## Actual execution, failures and recovery

`run_retention_control` validates the complete initial identity, current dataset,
frozen anchor, and bitwise no-control trajectory replay before deployment. It
keeps all applied full states, observations, actions and transition receipts.
It also records every solver receipt, actual one-step tangent error, and failed
condition's partial state. A partial path does not receive a misleading final
objective value or completed status.

`RetentionRunLimits` bounds horizon/geometry, solver iterations, action/state
magnitudes and elapsed CPU/wall time. Time checks are cooperative between
bounded numerical operations; they cannot interrupt a running BLAS call.
`cell_field_retention_experiment.py` supplies fresh sequential workers with the
same 15-second process CPU and 75-second wall caps for every arm. The inner
controller has 10-second CPU and 60-second wall budgets. A killed/missing worker
receipt is an explicit failed condition with retained logs. Its unreported
post-initial prefix is marked unknown, never counted as zero effect or success.

`stop_after` returns an explicit `paused` result for a declared recovery test.
`save_retention_run` exclusively creates an integrity-checkable directory,
stores the unchanged full-state checkpoint format and all trajectory arrays,
and writes its manifest last. `load_retention_pause` rejects failed/completed,
incomplete, stale, symlinked and checksum-mismatched checkpoints. A resume
verifies the original contract and deterministically replays the preserved
action prefix before computing the remaining controls. The replay is charged,
and the previous receipt remains embedded in the recovery record.

This is local mathematical replay. It is not distributed effect deduplication,
an exactly-once external tool guarantee, or an fsync/power-loss durability claim.

## Cost boundaries

Each call records total wall/CPU time and phase subsets, including admission,
failed solves, actual updates, probes, and recovery replay. Subsets must not be
added again to their enclosing total. Process RSS observations are cumulative
high-water marks, not incremental per-arm peaks or full-tree peaks. Reference
construction, Encoder extraction, input acquisition, persistence/load, process
startup and final scoring are outside the controller call. The experiment driver
records shared warmup/reference costs, full fresh-worker CPU/wall/RSS and
checkpoint/serving roundtrips. Owner CPU and reaped worker CPU are disjoint; nested
controller times are subsets of their workers. Acquisition/encoding and source
preparation remain separate earlier stages. No net-cost benefit is established
by these code tests or by the objective value alone.

## Source-only feasibility before any new experiment

`cell_field_retention_sources.py` reconstructs the exact default 768 historical
news exclusions, adds all 1,104 V3 evolution story IDs and all 512 PFT raw source
IDs, and closes **all raw story-ID and normalized-title edges** before checking
the proposed counts. It accepts additional source-only exposure manifests;
neither overlap between older cohorts nor their apparent names proves novelty.

The input manifests are byte-pinned. It never opens historical final-label,
prediction, score or model-checkpoint files. The pinned public raw archive's
categories are used only to reject conflicting components and calculate class
availability. It emits counts, source exclusions and shortages, not selected new
test labels. A count-only feasible answer remains conditional on the supplied
exposure inventory; the code does not assert that all past/prepared experiments
have been inventoried.

The actual original count audit is pinned at SHA256
`152ea104d9ff19f255c7a56399c4bcf62461ba9d634caa246a11e1b4d1312823`.
After the known-exposure closure, August has only 24/27/3/18 components per class,
below the requested 32 in every class. This failed July/August plan is preserved.
Before any new model outputs, source-selection protocol
`cell_field_retention_cohort_protocol.json` explicitly amended the future roles
to June 96 and July 128; April old roles 160 and May current roles 96 are unchanged.
The protocol was committed at `eebec960513dc9f58b830a8674a924a605fa532e`
before selection. The resulting 480 components have zero overlap with the three
pinned registered datasets under this full graph closure. Cohort receipt SHA256
is `7af61dfa851583d6d31c0163b5d9453841e21bef106058206731870d706364df`.

The stronger closure also finds 47 components shared between the default and V3
cohorts, and 118 between V3 and PFT; no default/PFT component overlap was found.
This is source-identity evidence, not an outcome-based attribution of older
performance. No exhaustive worldwide or unregistered-history exclusion is
claimed. These remain historical four-class news tasks with unknown foundation
pretraining exposure, not new task families or prospective deployments.

## Frozen empirical execution and scoring

`cell_field_retention_experiment_protocol.json` fixes six original states (two
head types, three seeds) and three arms each. All arms use the same new shared
Granite97m features, label-independent QR projection, warmup, Adam protocol,
reference, target, information and magnitude/time guards. Workers run sequentially
in a predeclared rotating arm order. The unchanged `cell_field_features.py`
extractor is reused with this new protocol hash and new predictor file.

The driver preserves all initial/final full optimizer states, serving-head
parameters, projection, reference arrays, feature identities, transition receipts
and every frozen prediction. Both complete-state and serving-head reloads are
checked and charged. These artifacts can support a later separately registered
same-graph multi-host inference comparison; no such result is implied here.

The scorer requires the exact prediction seal and all 18 completed conditions
before opening the new final-label payload. An incomplete census stops before
gold access. No best seed, best head, failed-condition deletion or retrospective
threshold search is permitted. Both heads are reported with 2,000 paired
category-stratified source-component bootstrap draws, conditional on the three
fixed fits. June and July contribute equal month weight.

Future qualification requires an upper one-sided 97.5-percentile bound below
zero for hinge-minus-legacy NLL. Retention qualification requires the old-test
hinge-minus-**original warmup** NLL upper bound to be at most 0.02 nats; comparing
only with an already degraded quadratic arm would not preserve the original
anchor. Both gates are required for each head, with Bonferroni across the two
predeclared heads. Bootstrap coverage is approximate; cost and broader scientific
gates remain separate.

## Local verification

From `qa/stem-bakeoff`, with the separately reviewed retention solver installed:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -W error -m unittest \
  test_cell_field_retention_run test_cell_field_retention_experiment \
  test_cell_field_retention_score test_cell_field_retention_sources \
  test_cell_field_retention_data \
  test_cell_field_retention test_cell_field_control -v
```

Tests use small, newly constructed numerical fixtures only. They check legacy
parity, the independent actual-state suffix calculation, original anchor,
physical scaling/masks, exact pause/save/load/replay, source graph closure,
unavailable counts, failure preservation and cost receipts. Passing tests do not
establish retention improvement, future-task gain, split/edge benefit or AGI.
