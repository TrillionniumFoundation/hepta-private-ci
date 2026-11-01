# Independent R15 owner and controller source review

This review reads `planner.py`, `execution.py`, `world.py` and their `Law`
contract. It distinguishes source-level consistency from a completed numerical
audit or a successful scientific confirmation. No confirmation data were used
to propose the changes below. The reviewer did not edit planner or execution.

## Reviewed source identity

The final read for this review has these SHA-256 identities:

| File | SHA-256 |
|---|---|
| planner.py | `2ca6033e52a0f941cd499230b04d9789bc761cf769ddb9a644de9641e09cc833` |
| execution.py | `28c8876e8e5fe2087d98883986aa8a04c9afb96d83fbfb89d3ea1930c824a4b0` |
| world.py | `e3f584515dfe5272122a6647aeb36c781505f4cd7f98f916cace2bc76206ed1f` |
| law.py | `d405c6dc629173b338828fef9bbe2b639cdc5a24de89023266786369d8997ef8` |

Later edits require their own identity and a focused review of the changes;
this file is not an approval of arbitrary later branch content.

## Findings resolved before source freeze

**Incomplete fixed-program family.** The first read contained seven programs
and omitted the legal `WAIT, WAIT, READ` late observation and four other
three-slot programs. A value planner could therefore use a useful schedule
unavailable to the purported strongest fixed comparator. The author added
`wait_wait_read`, `wait_read_read`, `read_wait_read`, `three_read` and
`refresh_read` before this final read. The resulting 12 programs contain every
legal sequence of READ/WAIT/REFRESH ending in an informative observation, with
total duration at most three slots, together with immediate STOP. Under the
full model, a final WAIT without a later observation gives the same deadline
forecast and adds a nonnegative cost, so it is unnecessary for this fixed
full-state comparison. This dominance argument does not automatically cover
information-destroying projected filters.

**Misnamed feature groups.** The first group was called `margin`, but its
features were mean phase index, content confidence/gap, time, prices and entropy;
it was not financial distance `V - V_b`. It is now `state_confidence`. The next
group is now `stop_value`: the extra feature is the best terminal prediction
under immediate submission, not the value of retaining future action options.
The fourth group remains a same-width ordinary nonlinear-feature control.

## Deadline and propagation contract

The source consistently scores the hidden content at the same public deadline,
three time slots after each query starts. STOP submits a forecast using
`max(p P(remaining_time) reward)` rather than scoring an easier current label.
READ consumes one slot and observes only on completion; REFRESH consumes two.
The owner advances every one of the four address distributions during every
action and during post-submission padding. It does not freeze nonqueried
addresses. The remaining padding is completed before starting the next query.

Public WRITE preserves the current phase distribution while setting only the
addressed content. The independent world preserves the actual hidden phase at
that same public event. At a shared boundary, query scoring and a step-three
observation use the left limit; the next query's public WRITE is then applied.
This prevents a future WRITE from answering a question before it is disclosed.
The world fixes its hidden trajectory before policy execution, and repeated
identical observation requests have the same keyed emission noise across arms.

The `.003 * action_duration` charge is a declared active-time tariff. Padding
after STOP advances physical time without that charge. Consequently it must not
be described as the entire physical-delay cost: every arm reaches the same
physical deadline. CPU, action tariff, physical time and energy are different
quantities, and no energy measurement follows from this fee.

## Information boundary and learned objective

The value planner receives only its own fitted law, current causal belief,
remaining slots and public fees. The scoring target is fetched only after the
actor has submitted its answer. The task owner can see the episode object and
hidden-world fingerprint; this is a source-level ownership discipline, not a
Python security sandbox. No current code path passes hidden states or targets
into `features` or `Planner.choose`.

`learn_controllers` deliberately uses fixed-STOP-prefix checkpoints. Each target
is an actual paired realized return difference for one READ or one REFRESH,
followed immediately by STOP, at the common deadline. Ridge regression on these
noisy realized gains is a one-observation policy experiment. It is not Q-star
supervision, full-policy Q-pi fitting, a policy-gradient estimator, or a proof of
policy improvement. At deployment, observations acquired in earlier queries can
change later prefixes; these differ from the fixed-STOP training distribution.
That distribution shift is a limitation to report, not a reason to replace
negative confirmation outcomes.

The exact primary planner is exact only for the current query under the supplied
finite model. It does not price the value of retaining an observation for later
queries in the six-query episode. Its Bellman recursion therefore does not
establish episode-wide optimality.

## Feature and implementation cost limits

The common `features` function computes the complete ten-dimensional vector,
including terminal STOP value and first-hit risk, before a feature group is
selected. Even `state_confidence` and `ordinary_dual` currently pay that common
feature-construction work. This is valid as a matched shared-computation
comparison if disclosed; it is not a measurement of the incremental cost of
adding risk, nor the cost of an optimized confidence-only implementation.

`Law` caches transition and event matrices. Total episode CPU includes accesses
and new constructions, but warm cache timing depends on previous episode/arm
execution. Cold preparation and reuse accounting must therefore be explicit in
the enclosing campaign. The same-matrix HMM must retain the same public
observations, posterior algebra and deterministic tie rules as HX; otherwise an
apparent difference can be numerical or procedural rather than scientific.

## Recovery and statistics limits

The current checkpoint restores beliefs, model identity, projection, method,
clock and operation counts. It does not contain the complete owner episode
cursor, partially completed action, cumulative fees, submitted answers or
pending observation contract. A belief round trip is not an end-to-end
crash/restart execution qualification. The scope must remain explicit unless a
separate owner checkpoint and actual resume test are added.

Each episode reports the mean of its six query utilities and a separate
all-queries-correct indicator. Queries and episodes within one fitted model are
not independent training replications. The eight independently calibrated fits
are the primary inferential units; paired worlds should stay paired across
methods. IID/OOD comparison multiplicity and any claimed mechanism family need
their declared correction. Calibration's raw validation likelihood choice is a
diagnostic; the campaign's actual-task-validation choice is a separate primary
selection and must be frozen before confirmation. Both free and same-matrix
ordinary candidate results should remain visible.

## Development computation retained

A source-review exploration evaluated fixed-program expected returns under the
default finite law over six elapsed times, four slot durations and four price
scales. By execution time the 12-program repair had already landed. It found no
positive omitted-program witness because the late-READ program was already in
the comparison family; its best recorded gap against that repaired family was
`-0.01475`, with elapsed time `1`, slot duration `.25`, price scale `.5`, and
late-READ value `.9407819597226215` versus STOP `.9555319597226214`. Its measured
inner CPU was `.208046798` seconds. This exploratory computation is not a
confirmation result or a justification for choosing any model or threshold.
