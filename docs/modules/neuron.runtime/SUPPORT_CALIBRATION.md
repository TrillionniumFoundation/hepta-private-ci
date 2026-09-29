# DecisionCell support calibration and experiment contract

## Implemented policy and compatibility

`codex-rs/hepta-neuron/qualification/decision_cell_calibration.py` owns the
package-local empirical fit. `hepta.decision-cell-joint-support-calibration.v2`
replaces the v1 sequential threshold search for newly fitted artifacts. The
runtime predicate is unchanged:

```text
supported = max(action_probability) >= minimum_confidence
            AND ood_probability < maximum_ood_probability
```

This is an advisory statistical predicate, not artifact selection, legal-action
masking, current result-use permission or independent OOD trust. The existing
inference-worker tensor consumer remains its only tensor execution implementation.
No wire codec, V2 durable format or production acceptance flag changes here.
Historical v1 artifacts retain their fitted thresholds and interpretation; do not
rewrite their receipts or identify them as v2 executions. Recalibration is a new
artifact with the original source/data/features retained as explicit inputs.

## Joint frontier rather than sequential local optima

The v1 algorithm first optimized the marginal OOD rule, then optimized confidence
inside that fixed rule. This can reject every row even when another threshold
pair satisfies both caps. For example, five correct in-domain rows at OOD=.05,
one incorrect in-domain row at OOD=.3, and two OOD rows at OOD=1, all at confidence
1, admit five correct decisions under the strict OOD threshold .3. The marginal
optimum admits all six in-domain rows, after which confidence cannot separate the
wrong row. This is a calibration-only counterexample, not a held-out model result.

V2 considers every distinct support set expressible by the bounded two-threshold
predicate. Confidence ties enter together; OOD ties obey strict less-than. For
at most 4096 owned, finite, normalized rows, it sorts confidence once and evaluates
cumulative counts at tie-group boundaries for each possible OOD threshold. Time
is O(n squared) and temporary storage is O(n); it does not enumerate row subsets.

Both existing empirical limits remain 1/20. OOD-only false accepts must satisfy
`20 * false_accepts <= total_ood_rows`; complete supported errors must satisfy
`20 * errors <= supported_rows`. The implementation uses integer count comparisons.
Confidence rejection cannot excuse a violated marginal OOD cap. Correctness is
action, applicable target, disposition and postcondition jointly correct. Every
accepted OOD row is an error regardless of its other labels. Unsupported rows do
not dilute supported error. Both labelled populations are required.

Among feasible pairs with at least one supported in-domain row, maximize the
supported in-domain count, then minimize complete supported error rate, then
prefer higher minimum confidence, then lower maximum OOD probability. OOD rows
never earn coverage credit. These deterministic tie breaks are part of v2.

No feasible pair produces `reject_all`: confidence=1, strict OOD threshold=0.
An empty supported error is undefined (`null`), not observed zero risk. Saturated
confidence=1 or OOD=0 cannot bypass reject-all. Existing returned marginal metrics
keep their meanings; supported coverage still counts all supported rows, whereas
the optimization objective counts only supported in-domain rows.

## Executable regression boundary

From `codex-rs/hepta-neuron/qualification`:

```sh
python3 -m unittest -v test_calibration_frontier test_calibration_tensor_frontier
```

The independent exhaustive oracle checks 512 seeded tied/untied fixture panels.
Other cases cover the sequential counterexample, infeasibility, the exact error
boundary, OOD and confidence ties, ownership/permutation and the 4096-row bound.
The tensor tests save actual safetensors, reload the existing `HeadTensorBundleV2`
and exercise its real support predicate. Fixture weights are not a trained base,
model-quality evidence, a fresh bakeoff or a target-host product qualification.
The existing qualification workflow discovers these tests without a new CI lane.

## Frozen experiment design and independent acceptance

Before new model execution, retain one immutable experiment manifest binding
source/tree, all model/code revisions, dataset/split digest, seeds, device,
precision, threads/concurrency, tokenizer/preprocessor, exact tensor graph,
calibration/evaluation versions, metrics, error budgets and stopping rule. Reuse
the existing complete-panel runner and artifact owner; do not add a second owner.
Attempt each frozen backend once and retain failures, timeouts and abstentions.

Train adapters/heads on training rows, select optimizer settings on tuning rows,
and fit temperatures plus v2 thresholds on calibration rows only. Freeze the
resulting bundle before independent evaluation. Test/native-probe outcomes may
identify a hypothesis for a NEW experiment but must not tune a threshold and then
be reused as its untouched acceptance evidence. Reusing retained base features is
head retraining, not a new encoder execution. Actual base/organ/cell/head consumption
must bind the exact artifact through the existing guarded product owner.

A production calibration claim requires independent, deployment-relevant in-domain
and OOD populations, their sampling unit and dependence treatment, predeclared
coverage and supported-error bounds, and familywise/multiple-candidate handling.
The empirical 5% fit constraints are not confidence bounds and are not a change
to any stricter production budget. Selection after inspecting multiple models
cannot reuse per-model confidence bounds as a simultaneous selection guarantee.

For future-window efficacy, preregister the artifact and analysis BEFORE the actual
calendar collection window opens. Retain collection timestamps and environment
outcomes, the full eligible-case denominator, abstentions, failures, unknown results,
latency and coverage, and compare against the frozen baseline under the same task
sampling. State the uncertainty and stopping rule before observation. Synthetic
future labels, retrospective relabelling, teacher agreement and repeated trials
of a failed case do not establish prospective efficacy. Evaluation may report
insufficient evidence without silently changing the artifact or acceptance budget.

Signed selection, current artifact admission, ordinary product authority, independent
acceptance and activation remain separate decisions. PR/run evidence records which
exact sources and artifacts actually executed; this contract grants none of them.
