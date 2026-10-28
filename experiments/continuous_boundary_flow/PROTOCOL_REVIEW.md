# Independent protocol review: continuous boundary flow

## Scope and claim limits

This experiment tests an implementation inspired by endogenous free boundaries and
continuation values. It does not reproduce He and Xiong's financial model verbatim.
Continuous readouts are continuous readouts; they must not be relabeled as spikes
from the existing sparse runtime. Native-runtime execution and Python training are
separate evidence scopes, and the report must say which path produced each result.

A synthetic maintenance task can establish numerical behavior, trainability, and
policy utility under its declared distribution. It cannot by itself establish
semantic memory, general intelligence, production efficiency, or biological fidelity.

## Design fixed before confirmation data

The run manifest is the machine-readable protocol. It must enumerate all arms,
training seeds, independent train/calibration/confirmation identifiers, task costs,
evaluation distribution weights, parameter budgets, cost scope, and the exact three
primary comparisons before confirmation evaluation. Save its SHA-256 with every
checkpoint/run. Do not change costs, primary pairs, seeds, or exclusions after
inspecting confirmation outcomes. Any later experiment receives a new protocol ID.

The three planned primary hypotheses are:

1. Task-value free boundary improves net episode utility over directly learned boundary.
2. Margin plus Call and Put features improves utility over the specified single-channel control.
3. Continuous flow improves utility over event plus reset dynamics.

The exact treatment/control arm IDs must be frozen in the manifest. Fixed boundary,
margin-only, margin-plus-Call, matched generic gates, the current sparse runtime,
generic continuous dynamics, and dynamic-programming reference remain visible in
all results, even if they outperform the proposed mechanism. They are not silently
replaced by weaker baselines. Other comparisons are descriptive.

## Fair access and computation

Every trainable arm receives the same public task state, remaining horizon, action
costs, and permitted history. Environment innovations, future realizations, and
held-out labels are never features. All arms use the same train/calibration budget
and optimizer-selection opportunity unless the difference is explicitly reported.

Distinguish public raw information from the computation used to transform it. If an
arm consumes dynamic-programming Q values, solved boundaries, or analytic risk,
record that solver's cost. A generic control for feature value must receive the
same derived features; a raw-input control answers a separate, clearly named question.
Match trainable parameter counts and hidden-state sizes for the principal
architecture comparison, or report the unmatched budget as a material limitation.
The oracle's dynamic-programming value is a reference, not an uncharged model input.

Boundary-only transmission carries no current state when the boundary is fixed.
Report which continuous values are actually consumed by downstream computation.
A native bridge must execute the current sparse runtime and use native-computed
activation in downstream action/readout calculation, rather than merely echoing a
Python-selected action. Cold replay starts from persisted inputs/checkpoints and
checks native state, readouts, actions, and event identity.

## Samples and pairing

The planned minimum is eight independent training seeds. This is a prototype
replication floor, not a power guarantee. Fix the actual seed IDs before evaluation.
Within each seed, all arms use paired exogenous episode innovations and identical
scenario parameters. Different actions may produce different states; sharing the
exogenous random stream remains valid pairing.

A practical fixed confirmation budget is 256 episodes per seed and arm, split
128 in-distribution and 128 out-of-distribution. If a different budget is required,
freeze it before confirmation and report it. Include an OOD mechanism change,
not solely a shifted mean. Train, calibration, and confirmation episode identifiers
must be disjoint. Calibration may fit a declared calibrator or choose declared
hyperparameters, but confirmation may not tune anything.

Every scheduled episode must appear, including failures and numerical divergence.
Do not drop difficult episodes, failed seeds, or unstable models. Record such cases
with the prespecified terminal penalty and stability-failure flag. Repeated ticks,
threshold crossings, and repair/reset events are correlated within an episode;
they do not increase the independent statistical sample size.

## Primary estimand and inference

Recompute gross task utility from primitive actions, outcomes, and the frozen cost
table. Recompute message/resource charges separately. Net utility subtracts only
the costs declared by the task protocol; wall time and energy must not be invented
or assigned a post-hoc coefficient to rescue an outcome. Report both gross and net.

First average episodes within each declared distribution; combine these averages
with fixed distribution weights; then average equally over independent training
seeds. Compute paired treatment-minus-control differences at the training-seed
level. The primary sample size is therefore eight, not the number of ticks or events.

For three primary comparisons, use Bonferroni familywise 0.05 two-sided Student-t
intervals: each interval has confidence 98.333333 percent and df = seeds minus one.
The frozen meaningful-benefit gate requires its simultaneous lower bound to exceed
0.005 net utility; positivity above zero is also reported as a separate diagnostic.
Report paired seed-bootstrap 95 percent intervals as a sensitivity analysis, with
a deterministic bootstrap seed. Do not call bootstrap percentiles exact. An
interval crossing zero means improvement was not established by this run. Do not
add seeds until a desired significance threshold is crossed. Small-sample t and
bootstrap intervals have distributional limitations, which remain visible.

Report ID and OOD utility separately even when the primary estimand averages them.
Report the per-seed differences so readers can assess consistency and outliers.

## Calibration, stability, and costs

Define each risk forecast's event and horizon. A no-intervention first-hit risk
must be scored against a no-intervention shadow outcome, not the failure outcome
after a policy repaired/reset the state. Specify prediction timing so no future
observation can leak into the forecast. Score Brier loss with equal episode weight;
use fixed probability bins for descriptive calibration tables/ECE. State whether
numbers describe raw or fitted/calibrated predictions and fit only on calibration.

Stability includes nonfinite values, bounded-state/readout violations, timestep
sensitivity, repeated-event/recovery behavior, and cold-replay mismatch. Finite
states alone do not establish spikes, phase transitions, or an attracting limit cycle.

Count training and solver construction once per trained model/run, not once per
episode. Count runtime calls, message values/bytes, solver calls, and state updates
from raw records. Record measured wall time separately for training, solver setup,
inference, and bridge execution. Warmup, compilation, process launch, serialization,
and audit overhead must have explicit inclusion/exclusion scopes. Event-message
sparsity and continuous-message volume are distinct. Operation counts are not
energy measurements; do not report inferred joules or hardware savings.

## Independent audit contract

The auditor reads the frozen manifest, persisted checkpoints, and raw episode
records. It recomputes utility, calibration, costs, and seed-level comparisons without
importing the training/evaluation summary function. Reported aggregate rewards and
claimed improvements are never trusted inputs. Source/manifest/checkpoint/record
hashes bind the evidence; hashing is integrity checking, not protection against
an adversary rewriting the entire trusted manifest and every artifact.

Reject malformed/nonfinite values, invalid probabilities/actions, duplicate or
missing scheduled records, missing arms/seeds, train/test overlap, checkpoint or
record digest mismatches, and inconsistent primitive-versus-reported costs/utility.
Tamper tests must exercise real failures: change a record, delete/duplicate a losing
episode, alter checkpoint bytes, or forge an aggregate. Rejection of aggregate-only
claims may mean ignoring them and recomputing the correct result. Keep audit tests
independent of the main summary implementation.

## Current review status

The design and claim limits above were written before confirmation results were
available. The independent auditor now checks full scheduled coverage, paired
per-window innovations, physical/state checkpoint chains, an independent first-hit
formula and conditional event-time inversion, frozen Q24 head scores, native NDU
action selection, referenced profile digests, and the selection seal. It recomputes
all rewards, byte charges, calibration metrics and eight-seed intervals. Meaningful
tamper tests cover omitted/duplicated observations, altered rewards, event times,
head scores, profile/checkpoint/cost files, selection inputs, and changed gates.

The native primary path is a research adapter around the unchanged source sparse
kernel/NDU. The complete chain includes bounded clipping, Q24 quantization and
discrete actions; this run does not establish an end-to-end differentiable SNN.
Generic controls use fixed random mixing and a fitted readout, not fully trained
recurrent networks. The direct boundary adds 20 fitted coefficients to the common
42-parameter head. The DP-derived channels consume model-solving computation.
All visited-state risk forecasts use the same analytic after-action predictor, so
Brier differences between controllers do not establish better risk learning.

Execution verdicts and deviations belong in the resulting audit JSON and study
report; this review remains frozen. A passing implementation/integrity audit does
not imply that any primary benefit hypothesis passed. The primary score prices
task outcomes and semantic messages; total compute costs are separately measured.
