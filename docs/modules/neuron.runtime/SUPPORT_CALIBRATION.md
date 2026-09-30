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

## Same-artifact calibration during real process consumption

The resident parent now reads the exact host-selected head manifest before
launch. Its SHA-256, base snapshot and runtime-profile digest must match the
already expected readiness identity. `HeadSupportRuleV2` is one immutable rule
used by the shared tensor consumer and by the parent receiving the IPC result.
The parent verifies canonical finite float32 scores, recomputes every calibrated
probability and the support bit, and rejects any mismatch. Float32 temperature
and threshold interpretation is unchanged, including confidence saturation and
strict OOD rejection at zero. No acceptance epsilon or threshold refit is used.

A late/contradictory result is not proof of remote non-execution. The process is
closed and reaped while the original operation remains available for exact-owner
reconciliation; neither a retry nor a model switch follows this error. Snapshotting
the rule prevents a later filesystem edit from changing a running invocation.
This check proves internal arithmetic consistency, not honest model execution,
independent calibration, provider authenticity or action authority. It does not
complete the missing learned transition/parameter heads of the Rust provider.

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

## Frozen-family count diagnostics and saved-artifact replay

`binomial_support.family_support_report` extends the existing count diagnostic to
an explicit complete family of 1--32 distinct candidate receipt identities. For
M candidates it allocates familywise alpha=.05 across 2M one-sided limits, one for
marginal OOD false acceptance and one for complete supported-decision errors per
candidate. Each limit uses Clopper--Pearson with alpha=.05/(2M). Missing or extra
candidates, duplicate receipt identities, malformed counts and empty populations
cannot improve the verdict. The original two-bound report and historical receipts
retain their original interpretation; this is a separate diagnostic profile.

At the existing diagnostic budget of 5000 ppm, a four-candidate family needs at
least 1013 zero-error independent trials **per candidate per population**, rather
than the single-candidate 736. This is a zero-error planning boundary, not a promise
that 1013 observed examples will qualify. Nonzero errors need larger samples.
Candidate results may be correlated: Bonferroni does not require independence
between models or risks. Binomial limits still require independent sampling units
within each target population. Repeated cases, synthetic source groups and a fixed
ID/OOD mixture do not prove the relevant deployment-population assumptions.

The existing bakeoff CLI's `family-support` command requires the original summary
digest and verifies all four configured backends through the existing receipt and
summary verifier. It reuses the frozen-feature loader and `HeadTensorBundleV2` to
reload actual saved weights and compute exact integer counts from test/OOD rows.
It neither refits thresholds nor infers counts from rounded receipt metrics. OOD
false acceptance is marginal: confidence abstention cannot hide it. Complete
supported errors include action, applicable target, disposition and postcondition;
every accepted OOD row is an error. The report retains full eligible denominators,
per-row prediction/support traces without prompt text, artifact hashes, original
training sources and the distinct current consumer source. It verifies the source
and complete family again before reporting and publishes a new private file only.

The report is retrospective synthetic-panel reanalysis, not a new encoder run,
training, independent calibration, a preregistration or prospective evaluation.
The trace makes the counted outcomes inspectable but does not independently
establish sampling, provenance authority, label correctness or rights. All trust,
selection, acceptance and activation flags remain false even when count limits
are met. Exit zero means the reanalysis executed, not that the counts passed.

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

## Concrete provider completion experiment: defined outputs before training

The next full-provider artifact needs an explicit, separately versioned graph;
existing `none-v1` parameter/stateless artifacts are not rewritten as complete.
Before training, freeze the following semantics and the exact consuming owner:

| Boundary | Required experiment input and acceptance observation |
| --- | --- |
| Text/target to Rust request | One host-owned projection binds raw text, ordered candidate IDs, target generations and observation frontier to both the private-process request and the typed Rust operation digest. Do not equate the two different digest domains. A trained reduction must define the admitted bounded feature vector; truncating encoder dimensions is not a learned projection. |
| Parameter head | Define units, coordinate frame, ranges, applicability and target-generation binding for every parameter. Derive labels from retained environment actions/outcomes, not a hash or constant placeholder. Parameterless examples cannot prove this head exists. |
| Temporal/transition head | Define the previous-state bytes and version, reset/episode boundary, next-state target and the meaning of drive/prediction Q24 tensors. Bind actual state bytes to their digest. An arbitrary nonzero digest or unrelated sparse checkpoint is not a learned recurrent state. |
| Numerical bridge | Fix float32-to-Q24 rounding, overflow rejection, score ordering, action masking and abstention before evaluation. Reject nonfinite or out-of-range values rather than clipping them into a plausible action. |
| Time and resources | Bind monotonic clock domain and unit conversion, dispatch deadline, queue age, complete latency and measured memory. Do not label fixture constants or Python process startup time as observed per-inference resource usage. |
| Recovery and migration | Use the existing Agentd owner/provider dispatch fence and witness. Reopen with the exact original request after each crash cut; unknown never redispatches. Old state stays read-only; migration has separate namespace/version and verified rollback compatibility. |

Collect environment-labelled episodes before fitting these new heads. Split by
source task/episode and relevant environment identity, not by neighbouring frames;
retain all failures and abstentions. Training, tuning, calibration, independent
acceptance and prospective windows have disjoint roles. The existing synthetic
command corpus remains a bounded regression/training experiment and does not
provide missing temporal or parameter labels. A new dataset requires its own
input admission and complete provenance; teacher output remains excluded until
provider and account-specific use rights are independently established.

First verify saved tensors and the actual encoder in an offline read-only
shadow experiment. Then run those same artifacts through the existing Rust
canonical owner on disposable state with no motor authority. Inject lost reply,
pre/post-dispatch cancellation, witness outage, process death and request
substitution before any isolated motor experiment. Only a distinct currently
authorized motor stage may perform effects. This order is an experimental design,
not an executed result, new runtime, production selection or migration receipt.
