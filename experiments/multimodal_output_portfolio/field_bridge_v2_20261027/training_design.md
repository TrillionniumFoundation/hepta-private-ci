# V2 development design review: identification before policy comparison

This review concerns the next development study after the frozen V1 result at
`e8ce0f538857f8bd869e275aa7fd258aa7989113`. It does not revise V1, use its
test outcomes as training labels, or certify a successful V2 before execution.
The executing protocol is authoritative when it explicitly adopts the proposed
choices below. Recommendations in this document are not a substitute for that
protocol or its source freeze.

## Why the first actuator was difficult to identify

V1 inserts rank-4 adapters only at `pixel_decoder.0`, `text_initial`, and
`text_projection`. Neither the upstream shared representation nor the digit
head changes. Its digit-head loss therefore has no adaptation gradient through
these modules. The pixel and caption losses still have real gradients, but
teacher-forced likelihood improvement need not cross an autoregressive token
decision boundary or change an image observer's class prediction. Eight-bit
PNG rounding adds another boundary. Pixel MSE is continuous between semantic
changes, but its weight is small in the actual utility.

The controller targets only 32 missing-condition pairs, whereas gradients cycle
through heavy noise, missing, occlusion, and clean conditions. On two held-out
trajectories, each seed's hard-value standard deviation was approximately
`6.7e-8`, `7.8e-8`, or `2.0e-7`. Those values are not an independent demonstration
of accurate prediction. A field predictor worse than current-value or a fitted
constant has no demonstrated predictive advantage. The rare hard-value jump
on seed 43's fitting trajectory further makes ordinary least squares on
absolute value vulnerable to extrapolating a discontinuity.

The low signal is an empirical finding about this actuator, schedule, panel,
and output objective. It does not show that every parameter field is
uninformative, or that upstream updates will necessarily produce useful gains.

## Development study with an effective actuator

A defensible next pilot expands the common adapter envelope to upstream
modules such as `fuse.0`, `coupling_cell.0`, and `digit_head`, alongside the
three output modules. Use one fixed rank, the same trainable parameters, the
same initial zero-output adapters, and the same base checkpoint in every
training method. A bounded grid of longer schedules and learning rates may be
screened on development data before the control experiment. Record all
attempts, including divergence and retention loss; a failed run is not removed
from the denominator.

Use a larger panel with all four declared conditions. Each condition should
use the same underlying panel pairs where paired comparisons are intended.
All condition replicas remain the same source-pair cluster. Save components
of the delivered hard score, token identities, observed digit decisions, and
PNG identities, not just a scalar surrogate. A panel with output changes but
no task improvement qualifies actuator sensitivity; it does not qualify a
useful learner.

Development selection may reuse known development sources. It must not read
the V1 test or retention results for checkpoint selection. A development clean
panel can constrain candidate choice, but independent retention certification
still needs a separate panel after selection is frozen.

## Proposed fixed qualification gates

The numerical values below were proposed before running the new pilot. They
are practical utility thresholds, not consequences of the parameter-field
theory. The executing registration must state which are adopted and must not
move an adopted threshold after observing its outcome.

| Gate | Proposed requirement | What it establishes |
|---|---|---|
| Actuator response | Each seed's final candidate value range at least 0.005; at least 5% of panel episodes change a caption semantic decision or image-observer digit decision relative to the unchanged generator | The chosen parameter/action envelope reaches resolvable output changes |
| Local action response | On held-out complete branch states, average action-value span at least 0.001, with at least 25% of states spanning 0.001 | There is an identifiable decision problem at the controller's timescale |
| Ordinary learning qualification | The development-selected ordinary recipe gains at least 0.005 pooled hard utility, no seed has a negative point difference, and development clean mean change is at least -0.01 | A useful ordinary update is available in the common candidate envelope |
| Prediction qualification | Field delta-value MSE is at least 10% lower pooled than the best declared baseline and does not worsen any seed | A useful forecast beyond trivial persistence or action averages |
| Choice qualification | Held-out action regret falls at least 20% relative to the fit-selected best fixed action, and selected action value improves by at least 0.001 | Forecast differences lead to a useful choice, rather than merely predicting a shared level |

Prediction baselines should include zero delta/current value, the fit-only
overall mean delta, and fit-only action-specific mean deltas. Compare to the
best baseline as declared, not to whichever is easiest to beat. Generic
equally sized features and richer optimizer features remain separate
representation controls; their results must be retained whether favorable or
adverse to the selected field.

Per-seed and trajectory-cluster uncertainty should accompany the gate point
statistics. With only a few independent trajectories, report that limitation
instead of presenting each sequential checkpoint as an independent draw.

## Identify causal action advantages at the same optimizer state

At each development branch boundary, clone all adapter parameters and the
complete optimizer state. Apply every registered action to an independent
clone, using the same next minibatches, augmentation marks, and noise. Measure
the fixed deployable policy's real hard value after the branch. Branch clones
must never inherit another action's updated momentum or parameters.

Predict the action increment

`delta_value(state, action) = value(after branch) - value(before branch)`.

This removes much of the irrelevant between-state level variation. The
no-update branch should preserve parameters, optimizer momentum, and value
exactly under deterministic replay. Current value is legally available only
on the declared training/development value panel. Its observation cost and
label queries must be charged to all compared learning policies.

Fit normalizers and models only on fitting trajectories. Freeze them before
opening held-out complete trajectories. The audit must contain all action
outcomes at each held-out state to evaluate ranking and regret; selected-action
rows alone cannot identify how well alternatives were ordered. An offline
action bank is appropriate here because it is development. It remains
forbidden as an input to actual future test deployment.

Evaluate both absolute delta prediction and decision regret. Good level
prediction can coexist with consistently wrong action rankings. A controller
choosing the current optimizer's ordinary action at every step may be an
acceptable practical outcome, but it does not demonstrate that the field
adds decision value.

## Retention and publicly observable fallback

A clean-domain fallback can be a valid deployed policy when its predicate
depends only on the input mask. For example, a full observed mask can route to
the original generator and original fixed policy. Such routing can establish
byte-for-byte clean preservation if its contract is tested on real outputs.
It does not demonstrate intrinsic retention of the changed parameters, and it
does not cover corrupted inputs or other retained capabilities.

If studied, give this assurance policy an explicit arm name and apply the same
information/action constraints to the simple history comparator. Do not use a
hidden evaluator split, label, source identity, or failure outcome to choose
the route. Keep ungated intrinsic retention results visible. A fallback must
not silently replace a failed retention hypothesis.

## Source-disjoint prospective evaluation

The recovered source constructor uses ordered counts:

`train=10000, validation=2000, evaluator=10000, retention=1000, test=2000`.

Source IDs and pixel hashes are deduplicated before splitting. Pair offset
`q` uses source positions `2q` and `2q+1`. Known V1 ranges are not the whole
history of possible reuse. Avoiding just those intervals is weaker than
excluding the complete original source pools.

Increasing only `retention_sources` and `test_sources`, while holding the
other counts and split seed fixed, preserves training, validation, evaluator,
and old retention/test prefixes. New retention pairs at offsets at least 500
and new test pairs at offsets at least 1000 then come from suffixes outside
the entire original retained/test pools. The raw checked MNIST assets already
contain these sources; no new dataset download is required.

The new corpus manifest changes and must be pinned. Verify suffix source IDs
and pixel hashes against the old complete split sets before evaluating
outcomes. This establishes disjointness relative to the recovered original
experiment. It is not a guarantee about every external project, new writers,
or a new task distribution.

## Conditions for moving to a new six-arm study

1. Freeze development qualification criteria and the actuator candidate grid.
2. Execute and retain the entire development pilot.
3. Check response, learning, and action-prediction qualifications separately.
4. Freeze one scientific design, the ordinary comparator, the field/generic/
   richer feature definitions, all runtime heads, and the complete source tree.
5. Only then execute selected actions on the new test and retention suffixes.
6. Retain the ordinary-plus-native and same-information history comparisons.
7. Report hardware timings separately from the registered logical tariff.
8. Keep negative or inconclusive scientific gates open; an engineering repair
   cannot by itself establish a comparative scientific advantage.

The resulting evidence can support a bounded empirical optimizer-field-control
claim. It does not establish field sufficiency, scalar FBSDE identification,
Riccati optimality, production ownership, or LLM-scale effectiveness.
