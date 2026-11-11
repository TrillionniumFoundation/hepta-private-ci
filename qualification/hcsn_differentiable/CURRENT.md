# HCSN research: current evidence and qualified scope

Updated 2026-11-11. HCSN is a **regenerative probability flow and content memory
network constrained by a shared generator**. Its numerical operators, learned
observation updates and content memory have separate evidence requirements.
The legacy He--Xiong equity kernel already exists and is not being reinvented.

The [P0--P5 evidence index](evidence/p0p5-20261110/README.md) binds each new claim
to exact source, runtime, data, configuration, model, raw execution records and
independent review. Historical source snapshots and failed attempts remain
unchanged. This page supersedes their status summaries, not their evidence.
The [terminal and verification follow-up](evidence/p0p5-followup-20261110/README.md)
preserves later observations separately: all 42 original attempts are terminal,
and all six HCSN attempts exhausted their budgets without establishing adequate
training. The earlier 472-file snapshot is unchanged.
The [resource and replay follow-up](evidence/p0p5-resource-replay-20261110/README.md)
adds independently checked resource curves, fresh full-D replay of all six
HCSN best checkpoints, and measured original-trace coverage. These completed
checks retain the training and whole-trajectory qualification limits below.
The [C2 launch snapshot](evidence/p0p5-c2-launch-20261110/README.md) records a
separately authorized extension of all six original HCSN fits. Its first
observation at 21:17:50 UTC confirms six actual optimizer-step witnesses and
gradient-enabled microbatch captures; terminal training and independent
trajectory audits remain pending in that snapshot. The
[CI and verification appendix](evidence/p0p5-ci-launch-closure-20261110/README.md)
binds later exact source trees and preserves the distinction between evidence
integrity, scientific fixtures and repository-wide CI.
The [C2 progress appendix](evidence/p0p5-c2-progress-20261110/README.md) and
[terminal numerical appendix](evidence/p0p5-terminal-numerics-20261110/README.md)
preserve later outcomes. The original numerical job ended at its unchanged
three-hour limit with 49/60 finite fixtures completed; its postmortem collector
completed separately. The [recovery appendix](evidence/p0p5-recovery-20261111/README.md)
restores the later original observation bytes after unavailable scratch contents
and explicitly inventories missing local preparation records. Its
[append-only link correction](evidence/p0p5-recovery-20261111/link-closure/CLOSURE.json)
retains the first failed check and restores two omitted context files under
their exact original names. At the latest
archived C2 observation, 2026-11-10 23:49:03 UTC, three fits remained active
and three had producer terminal reports. No all-six
independent C2 adequacy, new common-rate selection or scientific benefit is
inferred from those intermediate records. The subject-E exposure clarification
below supersedes the older progress appendix's phrase "E remains unread".

## Admission status

| Gate | Current evidence | Status |
| --- | --- | --- |
| Mathematical/API contract | Versioned definitions, drift regimes, reset and repeated-readout semantics | Defined and tested |
| Local numerical regression | 92 tests and four unchanged error-budget fixtures on the archived source | Passed within those fixtures |
| Actual training-domain accuracy | 49/60 terminal finite fixtures pass the original scaled gate; 12 tiny-gap pressure failures and six log-risk ordinary-FD holds remain | Selected fixtures pass; full training domain HOLD |
| Recorded quality and resource comparison | Original42/C1 results reproduced; C2 has three producer terminals and three active fits at the archived 23:49:03 UTC observation | All-six independent C2 adequacy and later resource view pending |
| Fair, sufficiently trained real-task benefit | Full-data development attempts and independent replay; output-interface diagnosis | HOLD |
| Endogenous optimal boundary | Independent finite DP/QVI fixture, three boundary groups | Finite fixture only; neural/continuum benefit HOLD |
| Real asynchronous multimodal benefit | Existing real localization data; new non-diffusion controls | HOLD |
| Repository-wide CI | Exact run identities recorded separately from local science tests | No all-green claim |
| Scaling, energy and production adoption | No measured comparative scientific benefit yet | Gated |

## P0: definitions and a reproducible source chain

The authoritative [model](MODEL.md) and [machine-readable contract](semantic_contract.json)
fix the objects below. The original financial equity, regenerative reference
and differentiable network are related through shared first-passage mathematics,
not by identifying their payoff functions or their boundary problems.

| Symbol | Meaning |
| --- | --- |
| `E` | Original He--Xiong equity under its financial cash flows and default boundary; implemented in `qualification/hcsn/reference.py` |
| `C_T` | Killed single-cycle running value plus survival-terminal reward; absorption payoff is separately declared |
| `U_T`, `U` | Finite/perpetual regenerative value with reset, delay, repeated events and terminal reward paid once |
| `F(T,x)` | First-hit probability for one killed active cycle |
| `G_q(T,x)` | Discounted first-hit mass; `1-G_q` is not survival |
| `M(t)` | Expected cumulative event count, potentially greater than one |
| `J(t)` | Instantaneous regenerative event-rate density `dM/dt`, not the first-hit density after regeneration |

The network's legacy `call`/`interval_value` is an interval reward feature,
not `E` or global `U`. Summing terminal-bearing interval features pays that
terminal feature repeatedly and is not a valid regenerative value calculation.
For the allowed single interval `dt <= refractory`, `risk` and
`expected_events` are the same conditional interval event quantity; they are
not two independent mechanisms. Dividing it by `dt` gives an interval-average
rate, not instantaneous `J`.

A pure readout query does not change state. Calling `forward` again with
`dt=0, observed=True` repeats observation conditioning and content writing.
Padding with `observed=False, valid_mask=False` preserves the physical state,
although the sequence-position counter advances. Zero elapsed time therefore
does not by itself mean a read-only query.

For the fixed continuum diffusion/regenerative reference with `sigma > 0`
and a fixed positive reset distance, negative drift has finite mean cycle
`d+x_r/(-mu)`. Zero drift hits almost surely but has infinite mean cycle time.
Positive drift has a nonzero escape probability and a finite total number of
future events almost surely. The constructor allows crossing zero; this does
not qualify a stationary firing-rate objective or a trainable domain.
These continuum asymptotics do not qualify the finite QPR chain: its fixed
returning-tail reconstruction can change long-run recurrence and event rates.

The formerly missing localization evidence was restored byte-for-byte from the
original native package. The new integrity checker validates size/SHA256,
ZIP CRC and member safety, and relative Markdown file links. Integrity is
separate from whether a scientific claim is justified. The earlier
[75-test/18-interface-fit record](evidence/localization-v2-20261108/README.md)
and [first math-closure snapshot](evidence/math-closure-20261108/README.md)
remain historical. They earn no new full-training or old S81 completion credit.

## P1: train-visited numerical qualification

[Training-domain tools](TRAINING_DOMAIN.md) capture actual priors/posteriors,
physical parameters, source/model/data/configuration digests, event counts,
valid observations and visited ranges. Truncated or partial traces cannot pass.
The independent reference uses 80-digit arithmetic, continuum basis integrals
and separately evaluated finite renewal continuations. Future observations are
disabled in those continuations: this checks the reconstructed starting law,
not equivalence to an exact continuous observation filter.

The [exact v8 recorder scope audit](evidence/p0p5-20261110/review/v8-recorder-scope-v1/RESULT.json)
establishes a further limit for fresh42. Its 4,096-record and 32-MiB caps retain
a chronological prefix of completed main-training microbatch forwards before
the optimizer step. Even ignoring the byte cap, microbatch size eight permits
at most 32,768 sample-position-layer states: 1.2243% of the 2,676,480 states
visited over the minimum thirty epochs. This is a theoretical upper bound,
not a measured retained count or a random coverage sample. Content state is
not retained, and the per-capture model digest identifies inner-network tensors,
not the complete model/checkpoint file. Final-checkpoint replay must therefore
be reported as supplemental final-model evaluation; it cannot restore missing
optimization-time visits or qualify the whole training trajectory.

The [actual terminal trace summary](evidence/p0p5-followup-20261110/original42/receipts-v1/HCSN-TERMINAL-SUMMARY.json)
now records only 343--346 retained records per HCSN fit before the byte budget
was reached, out of 537,856--547,072 seen record slots. All six traces are
explicitly truncated. These slot counts are not identical to valid sample-state
counts. The [original-label scan](evidence/p0p5-resource-replay-20261110/trace-coverage/recovery-v1/RESULT.json)
and [independent order/count review](evidence/p0p5-resource-replay-20261110/trace-coverage/independent-review-v1/REVIEW.md)
establish that all six fits together retained **2,066 record slots containing
16,492 valid sample-position-layer states**. Every retained `update_index` is
**0**: post-update retained slots and valid states are both **zero**. Main phase
and epoch 1 are derived from the original journal, manifest order and runner,
not literal epoch labels in the raw trace. The independent JSON review
reconstructs order and counts without rereading the large probability arrays.
It does not recover discarded states. Supplemental final-checkpoint exports
cannot fill this missing optimization trajectory.

A [separately frozen terminal-model plan](evidence/p0p5-followup-20261110/plans/final-hcsn-numerical-plan-v1/PLAN.json)
binds six checkpoints and 54 primary plus six supplemental finite cases;
its [independent input review](evidence/p0p5-followup-20261110/review/final-hcsn-plan-independent-review-v1/RESULT.json)
verifies the source, episodes and schedules. Preparation does not grant a
numerical pass or restore historical trajectory coverage.

The [original terminal execution](evidence/p0p5-terminal-numerics-20261110/numerical-audit/original-terminal/launch-receipt.json)
has now ended at its unchanged 10,800-second limit, with
`whole_budget_exhausted` and return code -9. The
[complete named roster](evidence/p0p5-terminal-numerics-20261110/numerical-audit/STAGE-ROSTER.json)
contains 85 complete artifact chains, one attempt without an outer completion,
and ten stages without an observed start. Of 60 finite fixtures, **49 pass the
original scaled gate and recorded source/input/resource checks**: all six
models' first eight best-checkpoint fixtures, plus seed101/rate.001's255-gap
case. One255-gap attempt is censored, four were not started, and all six
last-checkpoint supplemental fixtures were not started. The separate completed
metadata collector does not turn the original job into a completed audit.

The [frozen error index](evidence/p0p5-terminal-numerics-20261110/numerical-audit/INDEX.json)
records maximum scaled error **0.8571803953%** and maximum ordinary relative
error **5.0700834100%**. The latter is a rare discounted-count quantity and
does not use the same denominator as the scaled gate. The completed255-gap
case has reference count about3.0395444371, projected count about3.0531732829,
maximum scaled error about0.5472701%, and mass residual about1.1324e-14.
These are finite continuations of reconstructed starting laws with future
observations disabled. They do not qualify later C2 posteriors, every rare
tail probability, or a continuous observation filter.

The [independent JSON review](evidence/p0p5-terminal-numerics-20261110/numerics-independent-review/REPORT.md)
reconstructs all196 reported quantities and342 stage-artifact bindings without
rerunning a model or oracle. Its original reviewer filename assumption and
narrow closure remain separate. The original source/model/data identities,
487-member archive manifest, external collection finality and authenticated
archive readback are preserved. The full launcher wall is10800.006360915 seconds;
its10278.141465 seconds waited CPU is only a lower bound because the killed
active worker was not reaped into that accounting. Nested stage/launcher/
bootstrap costs must not be added together.

The [saved first-14 finite-case provenance](evidence/p0p5-c2-launch-20261110/numeric-context/first14-RESULT.json)
and [independent closure](evidence/p0p5-c2-launch-20261110/decision-provenance-review/RESULT.json)
bind the partial results available before the C2 decision. Their original
scaled gate passed; this is not completion of the 60-case finite roster.
The [bound rare-count case](evidence/p0p5-c2-launch-20261110/numeric-context/rare-count-original.json)
has reference count .0005011394183 and absolute error .00002075183836:
about **4.14% relative error**, despite passing
`abs(error)/max(1,abs(reference)) <= .01`. A scaled pass cannot be relabeled
as 1% relative tail or rare-count accuracy.

The [six-model pressure summary](evidence/p0p5-c2-launch-20261110/numeric-context/six-model-pressure-RESULT.json)
reads existing observer scalars: all six best models fail both tiny-gap
infinite-repeat value sentinels, giving **12 failures among 18 sentinels**.
The underlying 10,752 supplemental vector records are final-checkpoint
observations, not recovered training coverage. Finite bursts start from
posterior position 47 and use actual future gaps; the tiny-gap sentinels start
from positions 48/49 and repeat one gap forever. Their different starting
laws and horizons prevent a finite pass from cancelling a pressure failure.

The [log-risk investigation](evidence/p0p5-c2-launch-20261110/numeric-context/six-logrisk-RESULT.json)
and [independent JSON review](evidence/p0p5-c2-launch-20261110/numeric-context/logrisk-review/RESULT.json)
retain the failed/inconclusive ordinary-FP64 finite-difference gate. In each
model's representative query set, 96 derivative checks are unresolved and one
is above its resolution estimate: log G with respect to discount, where
ordinary FD differs by about `5.997e-10` against a `3e-10` gate. Autograd,
the 80-digit derivative and high-precision FD agree on that derivative.
Discount remains fixed in C2. Neither return code zero nor this diagnosis
grants general gradient qualification, and no tolerance was changed.

The [fixed-grid diagnosis](evidence/p0p5-terminal-numerics-20261110/mathematical-diagnosis/NOTE.md)
separates exact-source QPR projection from its actual fixed Gauss quadrature.
For a fixed interior uniform cell, exact adjacent transfer is proportional
to sqrt(dt), so `(T_dt-I)/dt` has no finite fixed-grid matrix-generator limit.
With finitely many strictly interior source nodes, the active off-diagonal
scaled limit instead vanishes at sufficiently small dt. These are distinct
limits, not a claim that the underlying continuous diffusion lacks a generator.
The shared-generator description constrains the continuous reference and point
kernels; it does not make the projected chain an exact semigroup.

A [separate48-case scalar diagnostic](evidence/p0p5-terminal-numerics-20261110/local-diagnosis/fixed48/REPORT.md)
ran once without models, posteriors or high-precision numerical-oracle calls.
At256 cells/order32, the two pressure time steps give free zero-drift adjacent
probability quadrature differences of+0.1354797523% and-0.0001402580933%.
They are outside the declared deep fixed-node freezing regime. Isolated phase
and equal-mass tail examples show separate information-loss mechanisms, but
none of these scalars attributes a fraction of the12 actual perpetual-value
failures. Underflows and engineering-resolution inconclusives remain explicit.
The initial infrastructure launch failed before Python; its replacement ran
the unchanged48-case program once. No qualification threshold was relaxed.

The new [finite-generator and rare-tail note](evidence/p0p5-recovery-20261111/math-recovery/rare-tail-review/NOTE-REVIEWED.md)
and [independent mathematical review](evidence/p0p5-recovery-20261111/math-recovery/rare-tail-review/REVIEW.json)
explain a further limit of a proposed finite-generator repair. A fixed finite
chain with finite rates has a polynomial small-time hit onset, whereas a
diffusion started a positive distance from its boundary has a negative
small-time logarithmic rate. Boundary densities with positive constant and
linearly vanishing limits give different leading powers. A fixed finite phase
chain also cannot exactly encode a strictly positive deterministic wait.
An exact discrete semigroup therefore does not itself qualify continuum rare
tails, reconstructed boundary laws or age transport. This new deduction does
not execute a replacement model or attribute the existing production errors.

The new stable log-first-hit primitive retains finite log F/log G when FP64
probability underflows. Twenty-one sampled cases include near-boundary,
short/long time, low-noise and drift-zero crossings, with first-order derivative
checks. This does not establish relative accuracy of every rare event, FP32,
second derivatives or the entire constructor range.

### Positive results and retained counterexamples

The [P1 summary](evidence/p0p5-20261110/p1/summary.json) and its authenticated
archive bind the following results to their exact configurations.

| Experiment | Measured result | Interpretation |
| --- | --- | --- |
| Endpoint 2, 135 grid/phase/gap combinations | 0/135 pass the original 1% all-basis perpetual-pressure gate | Repeating tiny gaps forever can expose fixed-grid projection error; this is not the actual finite data sequence |
| 128 active cells, endpoint 4.8, selected trained posteriors | Perpetual/short checks pass, but a 32-gap continuation reaches 1.6404% scaled count error | Rejected for that finite-schedule gate |
| 256 active cells, endpoint 4.8, content width 4, two short Adam updates | All 256 recorded A01 posteriors pass; maximum perpetual scaled value error 0.230232% | Scoped to the recorded model and visits |
| Same width-4 candidate, actual 128-gap continuation | Maximum scaled error across value/count/discounted count/active probability 0.702721%; mass residual 6.55e-15 | Selected finite continuation passes the original 1% gate |
| Same candidate, actual A04 burst containing 8e-7 and 1e-7 second gaps | Selected 8/32-gap continuations pass | Does not qualify arbitrarily repeated tiny gaps |
| Trainable mu/sigma/boundary/reset, two 16-event Adam updates on a 32-cell grid | Full discrete-forward AD/FD error at most 7.64e-11; continuum-basis AD/80-digit FD error at most 2.14e-14; value error 3.27336% | Gradient agreement passes; numerical value admission remains HOLD |

The 128-cell and 256-cell candidates were initialized and trained separately;
their learned posteriors differ. Their individual failure/pass results are not
a same-posterior grid-convergence experiment or a causal attribution to grid
size alone.

All reported scaled errors use `abs(error)/max(1,abs(reference))`. For a
reference below one this is an absolute-error scale, not a relative-percent
rare-event guarantee. Quadrature refinement and residual estimates are
measured sensitivities, not certified total error bounds.

The frozen width-4 candidate uses 256 active cells, one returning tail, 16
remaining-time cells, endpoint 4.8, refractory 0.2, tail rate 1, quadrature 32,
initial log standard deviation 0.08; actual physics are mu
-0.11999999999999998, sigma 0.35, log boundary 0, absolute reset
1.3771277643359572 and discount 0.15. These visits do not automatically qualify
a width-16 model, another trained checkpoint, positive drift, or another data law.

A separate [width-16 v6 audit](evidence/p0p5-20261110/p1/width16-v6/INDEX.md)
now binds the actual common-adapter, two-update model. All 512 recorded training
visits pass its perpetual-value checks; the maximum scaled value error is
0.229731%. Another 768 records are supplemental final-checkpoint evaluations,
not additional training visits. Two A04 records at tiny gaps fail the
infinite-repeat pressure gate, with scaled value errors 147.245% and 261.527%.
The total 1,278/1,280 pass count must not obscure those failures.

All five preregistered actual finite schedules pass the unchanged 1% scaled
gate. The 128-gap fixture has reference count 1.807107886; its largest reported
value/count/discounted-count/active-probability scaled error is 0.567008%, and
its mass residual is 5.88e-15. In the short burst, count error 0.104962% on this
scale corresponds to about 1.06% relative to its reference count below 0.1.
The finite pass therefore remains a scaled-error claim. The independent review
binds all five starting laws and gap lists. Neither this probe nor the earlier
width-4 experiment admits the eventual full-training checkpoints.

The first 256-cell job was externally killed with exit 137; its cause is
unknown and it remains incomplete. A separately bound immutable resume
completed the retained checks. The exploratory 135-case report lacked full
source capture; a fresh source-bound reproduction confirms its 0/135 result
and is the basis for the current claim. Neither history is rewritten.

## P2: real-data training and fair comparison

The [executable temporal-core protocol](../../proposals/localization-v3/README.md)
uses all 89,216 ABC training events and all 31,952 D development events in
nonoverlapping 256-event windows. A fresh official-data download and
preparation reproduced the original manifest bytes and all 484 episode hashes.
E is excluded before training preparation interprets its records. Historical
E schema/clock/global-gap exposure is still disclosed in the earlier evidence;
that history prevents claiming an untouched prospective test selection.

For each seed, every arm uses the same actual frozen 25-to-16 frontend and
16-to-11 output head. The roster is GRU, official CfC, official recurrent PLIF,
an analytic event-time LIF reference, official S4D-Lin, causal Transformer and
HCSN. The event-time method differentiates actual analytic crossing times
within a fixed active set; it is not a reproduction of the published EventProp
training system. This CPU FP64 Transformer is not a qualified optimized GPU
baseline. State grids, content dimensions, real-scalar parameter counts,
kernel work, all tuning opportunities and failures must remain visible.

An [operator-level profile](evidence/p0p5-20261110/review/attention-cpu-path-v1.md)
does confirm CPU flash-attention forward/backward and 1,809 one-thread MKL
DGEMM calls on the profiled cloud host for the actual 32-by-256 training shape.
That host's instruction set is not the native Xeon campaign host's identity;
the profile does not establish the latter's exact dispatch path or GPU/energy
efficiency.

### Completed raw-output diagnostic

The original campaign completed **36/36 full-data attempts**: six baselines,
three seeds and two learning rates, with 30--40-epoch bounds. Only **2/36** met
the predeclared combined training-adequacy criterion. Independent review
recomputed every saved-logit metric, checked model/data/update/source identities,
and reproduced one fresh forward per core exactly. All 36 evidence checks
passed. A verified execution is not an adequately trained model.

The frozen random head imposes materially different confidence limits on
bounded core outputs. GRU and default CfC are bounded; PLIF emits binary
spikes. Independent analysis found a strict argmax witness for every class in the
declared output-domain relaxation: there is no algebraic class obstruction
from the head alone. This does not show those recurrent dynamics can reach
every witness. It did find low achievable confidence for some output domains. This motivates a common learnable identity-initialized
linear adapter in every core, charged to its parameter and compute cost.
The added adapter is functionally a trainable linear readout despite the
stored common head remaining frozen. It does not prove that the head explains
every training failure.

A fresh adapter pilot uses the same training-only 256-update memorization
criterion, then resets for one full epoch. Five of six baseline cores pass
that diagnostic. PLIF did not pass the raw-spike 1,024-update extension or the
eight-configuration 256-update grid (seven completed, one timed out). Fresh
membrane and EMA-spike-trace readouts both passed with 1,024 updates. The
spike-trace candidate's first observed passing checkpoint was update 768,
versus 1,024 for membrane;
its final diagnostic accuracy/present-class F1 were 0.9921875/0.9905527.
It uses the declared event-indexed recurrence trace = 0.75*trace + 0.25*spike.
This selects a trainable SNN configuration without lowering the criterion; all
extra diagnostic opportunities are charged. One main epoch is not sufficient
training, and cross-host timing changes are not adapter speedups. Historical
raw-output results remain an interface diagnostic, not a mechanism ranking.
The current runner separates strict best-checkpoint selection from the plateau
stopping threshold; the original run keeps its original checkpoint rule.

### Fresh 42-fit campaign and explicit cap continuation

The [frozen v8 plan](evidence/p0p5-20261110/p2/campaign-v2-plan.json) and
[original native launch receipt](evidence/p0p5-20261110/p2/campaign-v2-native-launch.json)
bind seven cores, seeds 101/211/307, and learning rates .001/.003. Every arm
receives the same learnable 272-parameter adapter, frozen common tensors,
effective batch 32, and training-only diagnostic checked every 64 updates up
to 1,024. Main training has 30--100 epoch bounds, .002 significant-improvement
delta and ten-epoch patience. D macro-F1 .30 is the predeclared resource-to-quality
target; it is a development selection target, not confirmation performance.

The original controller uses nine workers, with six HCSN fits first in its
roster. There is no separate baseline semaphore; baseline concurrency can
grow after HCSN workers finish. Its nominal per-fit wall ceiling is 14,400
seconds, but a 15,000-second campaign deadline shortens later fits' actual
grants: `min(14400, 15000 - dispatch_elapsed)`. Comparisons must use each
outer receipt's actual hard ceiling and
retain censoring, rather than claiming every fit received four hours.

The campaign was dispatched at 14:49:15 UTC. A recovered
[read-only native snapshot](evidence/p0p5-20261110/p2/native-recovery-v2/native-status-query-stdout.json)
at 16:40:46 UTC observed all 36 baseline attempts completed: 26 met the declared
adequacy heuristic, seven reached the epoch cap and three reached a plateau
but failed memorization. The retained
[18:01 progress observation](evidence/p0p5-20261110/p2/native-hcsn-progress-1801-v1.json)
was intermediate. The later
[original terminal result](evidence/p0p5-followup-20261110/original42/terminal-small/campaign-v2/RESULT.json)
completes all 42 attempts. All six HCSN diagnostics passed and 46--47 complete
main epochs were recorded, but each fit returned a handled budget failure
with code 2. Recorded inner wall exceeds the soft wall limit while RSS remains
below its limit. No HCSN fit reached the declared plateau condition. Complete
outer costs, last complete checkpoints and partial interrupted work are retained;
the original jobs were not restarted or relabelled as converged.

At least one observed baseline reached its 100-epoch cap while still improving.
A separately declared C1 extension restores complete model/configuration,
optimizer, RNG and plateau state, preserves the inherited best checkpoint,
and uses only the original fit's remaining actual wall allowance. It adds no
new seed, learning rate or diagnostic. Its validation costs are recorded;
actual continuation steps, preflight/controller work and extra calendar time
must be reported as a separate phase when it runs.
It is not retrospectively treated as the original 100-epoch protocol.

The [C1 delivery receipt](evidence/p0p5-20261110/p2/continuation-delivery-tests.json)
reports 24 passing implementation tests: the existing 13 core tests and 11
continuation tests. Five cores match split and uninterrupted complete states
on synthetic data. The [native controller's nine tests](evidence/p0p5-20261110/p2/continuation-controller-v3-tests.json)
cover shortened actual limits, launch accounting and failure/timeout cleanup.
The [actual C1 controller report](evidence/p0p5-20261110/p2/native-c1-completed-v1/RESULT.json)
records seven eligible continuations completed between 16:52:59 and 16:56:17
UTC. All seven report the declared adequacy condition, with cumulative epochs
101--235, unchanged source/common weights and no missing terminal record.
The original baseline study plus C1 therefore reports 33/36 adequately trained
configurations. The three memorization failures remain failures. The
[independent baseline/C1 audit](evidence/p0p5-20261110/review/baseline36-c1-native-v1/v2/output/SUMMARY.json)
confirms that count. It rechecks the exact inputs behind all thirty-six
previously audited baseline records and separately verifies all seven C1
chains, including saved configuration/optimizer/RNG states, journals and fresh
full-D logits. The original C1 execution did not save a resume-start snapshot;
the review cannot directly compare an unrecorded state before its first step.
This evidence does not grant full numerical-domain or scientific-benefit credit.

The [initial strict audit](evidence/p0p5-20261110/review/baseline36-c1-native-v1/v1/output/SUMMARY.json)
passed all thirty-six originals but rejected all seven C1 records because two
clock samples differed. Its failed result and costs remain intact. The separate
supplement verifies each original early/late sampling interval and its complete
outer-process bound, then supplies the later time to the unchanged helper.
Quality cutoffs and charged cumulative costs retain their original later
timestamps; no original log is rewritten or timing tolerance enlarged.
The [complete parent/C1 archive](evidence/p0p5-20261110/p2/native-c1-completed-v1/ARCHIVE-RECEIPT.json)
preserves all seven chains in 252 members, including source, checkpoints,
optimizer/RNG states, logits and journals. Its
[draft upload receipt](evidence/p0p5-20261110/p2/native-c1-completed-v1/DRAFT-UPLOAD-RESULT.json)
verifies all 45,425,233 bytes by authenticated readback; this is an archival
result and does not replace the independent chain audit.

The original C1 producer sampled the phase clock twice per epoch record.
A [separate prospective source fix](evidence/p0p5-20261110/publication/continuation-single-clock-pr.json)
uses one sample for both phase and cumulative cost. Its
[regression evidence](evidence/p0p5-20261110/p2/continuation-single-clock-v1/SUMMARY.json)
records the new test failing on the old source and all twelve continuation
tests passing on the changed source. This source was not used by native C1;
the original logs and strict-review failure remain historical evidence.

A [C2 feasibility package](evidence/p0p5-20261110/p2/c2-feasibility-v2/FEASIBILITY.md)
tests complete-epoch recovery and proposes a separately accounted resource
extension. Independent [metadata counterexamples](evidence/p0p5-20261110/review/clock-c2-independent-v1/COUNTEREXAMPLES.json)
identified three guards missing from the retained first version; the second
version rejects any earlier plateau stop, negative clocks and negative AdamW
second moments. Its twenty-one synthetic tests were preparation only.

The subsequent [C2 execution chain](evidence/p0p5-c2-launch-20261110/README.md)
retains two further counterexamples and their corrections: accepting return
code zero without a valid result, and treating a matching trace row count as
sufficient coverage. Native v3 then passed 53 software tests and six real
parent bind-only checks. Reporting-only v4 received five targeted cloud tests
and independent source/AST review; it is not represented as another 53-test
native preflight. Its [exact source capsule](evidence/p0p5-c2-launch-20261110/launch/source-v4.zip)
and [root decision](evidence/p0p5-c2-launch-20261110/decision/DECISION.json)
were fixed before any new production optimizer step.

The six original candidates were dispatched at 21:13:44 UTC. They resumed
only complete epochs 46,47,46,47,46,46, discarding already executed partial
updates 7,5,10,1,8,10 without a cost refund. Each fit has a 43,200-second
cumulative active-wall cap including its complete original outer process;
imports, recording, evaluation and finalization consume the same allowance.
The maximum is 200 complete epochs, with the inherited plateau rule and no
new seed, learning rate, physics, memorization diagnostic or confirmation-E
access. The 600-second reserve is an early-stop heuristic inside the cap,
not a guarantee that final capture and evaluation can finish.

The [first-step index](evidence/p0p5-c2-launch-20261110/FIRST-STEP-INDEX.json)
binds all six pre-step complete-state producer witnesses and actual
gradient-enabled captures, totaling 1,536 time rows and 12,182 valid sample
states in the capture receipts. Each corresponding optimizer step completed.
The observer copied receipts and events, without reading the complete
probability arrays or independently loading checkpoint tensors. Terminal
source/state/epoch-chain, trace and fresh full-D audits remain required.
Sparse optimization captures and separate no-gradient checkpoint replays are
distinct evidence; neither grants whole-trajectory numerical admission.
The original 300/900/1,800-second quality curves remain unchanged. C2 is a
separate longer-resource/calendar phase, with no adequacy or benefit credit
before terminal evidence and independent confirmation.

The [23:49:03 UTC metadata index](evidence/p0p5-recovery-20261111/training/V8-METADATA-INDEX.json)
binds the exactly recovered v8 observation and its preceding archive chain.
It observed three active fits and three producer terminals; model/probability
arrays were not read. The separate retained native status response ending at
2026-11-11 00:08:14 UTC still reports the same original C2 job running. Neither
dated observation establishes its subsequent state.
The following individual best scores are intermediate D-selected values,
not a new common-LR comparison or confirmation result.

| Seed | LR | Complete epoch | Strict best D macro-F1 | Observed state |
| --- | --- | ---: | ---: | --- |
| 101 | .001 | 77 | .2793821424 | Active |
| 101 | .003 | 76 | .3878342597 | Producer plateau; independent C2 audit pending |
| 211 | .001 | 77 | .3005516559 | Active |
| 211 | .003 | 50 | .3910932361 | Producer plateau; independent C2 audit pending |
| 307 | .001 | 78 | .2708893398 | Active |
| 307 | .003 | 72 | .3498305889 | Producer plateau; independent C2 audit pending |

The [first actual terminal report](evidence/p0p5-c2-progress-20261110/first-terminal/payload/fit/result.json)
records three added complete epochs and 36 new updates for seed 211/rate .003.
Its selected epoch 40 checkpoint and D metrics are unchanged from the original
run, so this continuation yields no selected-quality improvement. Producer
adequacy is not yet independent C2 admission. Its
[complete-attempt ledger](evidence/p0p5-c2-progress-20261110/first-terminal/COST-SCOPE-ADDENDUM.json)
charges 1266.1814752598293 seconds of C2 wrapper time, including the post-child
verification tail, for a cumulative 15643.131377664628 seconds. Exact cumulative
CPU remains unknown; the new child's measured wait4 CPU is 1263.453444 seconds.

The [two later terminal records and costs](evidence/p0p5-recovery-20261111/training/V8-METADATA-INDEX.json)
add seed 101/rate .003 at 76 complete epochs and seed 307/rate .003 at 72.
Their original-plus-C2 complete-wrapper wall bills are 23128.517257251777 and
22286.68389489292 seconds, respectively. Their strict-best epochs are 74 and
62. Strict best and the .002 significant-improvement anchor remain separate;
a small strict improvement need not reset the plateau counter. These are
producer development results, not independent terminal admission or a new
common-rate comparison. Final wrapper overhead is not assigned to earlier
quality-crossing timestamps, and missing historical CPU is not zero-filled.

The [terminal auditor](evidence/p0p5-c2-progress-20261110/terminal-auditor/PLAN.json)
is frozen and has 28 synthetic tests, but has not audited actual C2 outputs.
Its 1800-second core envelope requires all six real terminals, durable native
receipts, absent/zombie workers, immutable controller inputs and a new bound
execution decision. The [later resource plan](evidence/p0p5-c2-progress-20261110/resource-plan/PLAN.json)
preserves historical curves and charges every original/C2 attempt. Final
wrapper tails belong in the bill, not retroactively in earlier quality-event
timestamps. Neither preparation grants a new selection or an adequately
trained comparison while the original C2 roster is incomplete. The
[recovery inventory](evidence/p0p5-recovery-20261111/recovery/SCOPE.md) preserves
the uncommitted preparation gaps. Partial source recovery does not authorize
the old resource program. Replacement preparation needs its own complete
source, validation and binding under the unchanged 120-second analysis limit.

### Development outcomes and HCSN censoring

The [resource analysis](evidence/p0p5-resource-replay-20261110/resource-analysis-v1/output-v1/REPORT.md)
binds all 49 original/C1 reports and independently recomputes 2,969 confusion
matrices: 2,927 complete-epoch observations and 42 explicitly timed
before-training evaluations. Its [independent review](evidence/p0p5-resource-replay-20261110/independent-resource-review-v1/REVIEW.md)
agrees on both the original 42-attempt view and the separate view adding C1.
The analysis plan was frozen after terminal scores were known; the 300/900/1,800
second cuts and F1 target .30 were already declared in the original plan.
D remains tuning data, and confirmation subject E has not been scored in this
campaign. The [E exposure correction](evidence/p0p5-terminal-numerics-20261110/SCOPE-CORRECTIONS.json)
supersedes "E remains unread" in the historical progress snapshot: the legacy
full-data loader interpreted E schema, coordinates, label validity, clock and
global gaps. This preparation and C2 do not interpret E; historical feature/
schema blindness is not claimed. The separately proposed subject-E evaluation
is unexecuted. It would not complete the original formal recipe of12 tuning
configurations times3 seeds followed by five fresh confirmation seeds.

Each cell below is mean best recorded D macro-F1 at or before the original
per-fit process-wall cutoff, across all three seeds at one common LR selected
from .001 and .003. Both LR rosters remain in the result; every defined cell
selects .003. Imports, diagnostics and cold-cache work consume the same budget.

| Core | Original 300 seconds | Original 900 seconds | Original 1,800 seconds |
| --- | ---: | ---: | ---: |
| GRU | .4250 | .4250 | .4250 |
| CfC | .3490 | .3490 | .3490 |
| Surrogate-gradient PLIF | .1500 | .1500 | .1500 |
| Analytic event-time LIF | .1841 | .3130 | .3130 |
| S4D-Lin | .3597 | .3597 | .3597 |
| Causal attention | .4026 | .4026 | .4026 |
| HCSN, budget-censored | Missing | .0256 | .1086 |

Missing means no completed evaluation, with no zero filling or interpolation.
None of the six HCSN candidates completed an evaluation by 300 seconds. At
900 seconds, the selected HCSN roster contains two complete-epoch results and
one explicitly timed before-training evaluation. The separate C1 view changes
only the S4D-Lin mean in these three columns, to .3669. C1's extra calendar
phase is not retroactively part of the original 100-epoch protocol. These
at-most process-wall budgets do not imply matched energy, CPU grants or
simultaneous calendar completion.

The terminal table uses the separate C1 view and first strict-best
complete-epoch metrics. Each selected baseline roster uses LR .003 and has
three adequate chains; the selected HCSN roster also uses .003 but has none.
The retained [earlier six-core audit table](evidence/p0p5-20261110/review/baseline36-c1-native-v1/v2/output/CORE_TABLE.json)
and its original clock samples remain unchanged.

| Core | D macro-F1, mean +/- sample SD | Median first observed D F1 >= 0.30, seconds | All six original fits plus C1 process-wall sum, seconds |
| --- | --- | --- | --- |
| GRU | 0.4250 +/- 0.0112 | 55.6 | 784.3 |
| CfC | 0.3490 +/- 0.0161 | 155.5 | 1,701.9 |
| Surrogate-gradient PLIF | 0.1500 +/- 0.0323 | Not all seeds crossed | 1,309.0 |
| Analytic event-time LIF | 0.3130 +/- 0.0419 | Not all seeds crossed | 3,927.0 |
| S4D-Lin | 0.3669 +/- 0.0243 | 48.7 | 817.1 |
| Causal attention | 0.4026 +/- 0.0487 | 66.3 | 1,461.6 |
| HCSN, budget-censored | 0.3576 +/- 0.0318 | 9,587.0 | 86,261.1 |

The HCSN row uses the
[six original terminal reports](evidence/p0p5-followup-20261110/original42/receipts-v1/HCSN-TERMINAL-SUMMARY.json)
and each candidate's strict-best complete-epoch D metric at common LR .003.
Its three selected scores are .353904163, .391093236 and .327756295, at best
epochs 47, 40 and 43. They are not the last-epoch scores. Unlike the selected
baseline rosters, **zero of these three HCSN fits meets training adequacy**.
Across both learning rates, **all six original HCSN fits remain inadequate**.
Their budget-failure reports legitimately contain no final selected-logit
artifact. The [independent full-D replay](evidence/p0p5-resource-replay-20261110/full-d-replay/REVIEW.md)
therefore binds each best checkpoint to its original strict-best epoch. All
six replay runs evaluate all 128 D windows and 31,952 valid events, with
identical confusion matrices and maximum scalar metric difference 2.22e-16
under the predeclared 2e-12 gate for macro-F1, accuracy, NLL, Brier and ECE.
Source, checkpoint, data, common tensors and
physics are checked before and after; new logits, labels and source-row order
are archived. No optimizer is constructed, restored or stepped, and no
backward pass or E evaluation is performed. This confirms same-development
reproducibility, without granting training adequacy or numerical admission.

The cost column charges both learning rates and all seeds, including failed
memorization and C1. It sums overlapping process durations, not campaign
calendar time. Each original fit's startup and diagnostics are already
included in this column; historical tuning, extra probes and independent
review are separately charged in the cost ledgers. Target times use the first observed
complete-epoch crossing of .30 uniformly across cores; unlike the budget
quality table, they exclude before-training evaluations. They are sampled
epoch times, not exact continuous crossing times. The analysis retains the
earlier table's separate later report-clock samples and their differences.
Uncrossed seeds stay censored; a median is shown only when all three selected
seeds cross. Original per-epoch process CPU is measured, but C1 cumulative
CPU is only a lower bound because the original parent's full exit CPU is
unavailable. CPU is not substituted for the wall-budget axis. These outcomes
do not complete a sufficiently trained seven-core comparison and provide no
independent-confirmation or energy result.

The [native attention profile](evidence/p0p5-20261110/review/native-attention-path-v1/worker-result.json)
also observes CPU flash SDPA forward/backward on the actual Xeon E5-2673 v3
host, with AVX2, FP64, one Torch thread and one interop thread. The fixed
32-by-256 ABC batch contains 8,134 valid events and uses an explicit causal
mask. Original source and checkpoint bytes remain unchanged. The
[outer receipt](evidence/p0p5-20261110/review/native-attention-path-v1/RESULT.json)
charges the complete instrumented process; this proves the native dispatch
path, not an optimized GPU result, an ordinary training-time measurement or
an identified assembly-level BLAS microkernel.

### Cost accounting

The [original42 terminal controller](evidence/p0p5-followup-20261110/original42/terminal-small/campaign-v2/RESULT.json)
records 14,378.056994 wall seconds, 95,769.851164 summed fit-process seconds,
95,753.221092 child CPU seconds and 141.524450 controller CPU seconds.
The [complete launcher](evidence/p0p5-followup-20261110/original42/receipts-v1/launcher-final-original.json)
also includes source extraction and its native thirteen-test child: 14,383.004945
wall seconds and 95,899.502808 child CPU seconds. These enclosing and nested
scopes overlap. The [follow-up cost ledger](evidence/p0p5-followup-20261110/COSTS.json)
also retains archive, authenticated readback and independent-review costs.
The [resource/replay cost ledger](evidence/p0p5-resource-replay-20261110/COSTS.json)
adds the resource calculation and independent review, six full-D replays,
trace-label recovery, publication attempts and hosted-artifact retrieval.
The full-D controller records 730.309 wall seconds and 735.747 child CPU
seconds. Its enclosing bootstrap includes that controller, extraction and
native validation; these scopes must not be summed. Failed publication and
retrieval attempts remain charged. Complete hosted-job CPU, physical energy,
billing and historical totals remain unknown.
The [source and cost closure appendix](evidence/p0p5-resource-closure-20261110/README.md)
retains later verification/publication failures, successful committed-tree
readbacks and nested hosted-fixture timers. These do not establish complete
hosted-job or research totals, or certify this later CURRENT edit.

The raw campaign controller wall time was 2,040.85864 seconds; summed attempt
wall time was 5,573.793 seconds and measured child CPU time was 5,564.147 seconds.
These are different, overlapping accounting scopes and must not be added.
Unknown physical energy, VRAM and historical provider charges remain null.

Exact frozen-table caching keys full physical/configuration tensor identity
and exact time-gap bits. It rejects learnable physics, starts cold for each
fit and clears after checkpoint loading. It changes computational reuse, not
the underlying numerical law. Weighted microbatch accumulation keeps the
whole effective-batch denominator and performs one clip/optimizer step.
The current core implementation has thirteen local behavior tests, including
cached and uncached values/gradients, one-ULP gap separation,
full-batch/microbatch Adam equivalence, weighted epoch aggregation and complete
PLIF checkpoint reconstruction. The earlier ten-test source and its receipts
remain historical. These tests do not grant a larger numerical domain.

The cost probe for the 256-cell, width-16 model and common adapter completed
two 256-event Adam updates: cold step 11.8958 seconds, warm step 1.43981 seconds,
27 cached tables using 16,452,072 tensor bytes, and process peak RSS
925,540,352 bytes. It is a two-update cost measurement, not a complete epoch or
a sufficiently trained HCSN result. The
[recovered original cost records](evidence/p0p5-20261110/p2/native-cost-originals-v1/README.md)
now bind the earlier source-v3 batch-32 failure: zero completed updates,
48.838508 seconds inside the profile, 52.017043 seconds for the complete child,
4,383,834,112 bytes peak RSS, and handled exit code 2 after a CPU allocation
failed under an 8 GiB address-space limit. This was the earlier configuration
without the common learned adapter; it is neither an OS-kill claim nor a
measurement of the later v6 configuration. Its full three-attempt controller
and both successful 128-cell probes are charged in the cost ledger.
The bounded observed resource curves above are now reproducible. Sufficiently
trained seven-core comparisons and comparative energy results remain HOLD.

Separate native effective-batch-32 probes measured microbatch four and eight.
Their warm update times were 25.227 and 21.676 seconds, with peak RSS about
2.307 and 3.671 GB; their losses and gradient norms agreed to roundoff.
The [original micro4/micro8 records](evidence/p0p5-20261110/p2/native-cost-originals-v1/RECOVERY_INDEX.json)
have now been recovered and matched to the prior
[derived result view](evidence/p0p5-20261110/p2/hcsn-effective32-derived-summary.json).
Their previous cost row now points to original bytes; recovery does not charge
the two executions a second time.
These two-update probes do not establish a full-epoch speedup across hosts.

Per-epoch process CPU includes imports; the original fit's final CPU field
subtracts a later starting counter. Those scopes cannot be silently summed.
C1 active-process wall excludes gaps between phases and must be distinguished
from full calendar time. The [cost ledger](evidence/p0p5-20261110/COSTS.json)
keeps controller, process, algorithm, tuning, failed-attempt and independent
audit scopes separate, with unknown energy and incomplete totals left unknown.
C1 adds 198.271888 seconds of controller elapsed time and 499.411218 seconds
of measured child CPU, including its native preflight. Summed continuation
child wall is 492.048214 seconds; these overlapping scopes are not added.

## P3 and P4: independent controls

The [finite QVI oracle](../hcsn_qvi/README.md) compares a fixed threshold,
a directly optimized soft threshold and a finite-state DP/QVI policy.
Their fixture values are 6.02067, 6.20332 and 6.28382. The Bellman residual is
8.89e-16, independent DP disagreement 9.48e-10, implicit cost-gradient error
1.40e-11 and infinity-norm condition number 682.46. Active-set changes invalidate
the fixed-policy derivative. Refinement changes the boundary and condition
number. This is a bounded reflecting CTMDP fixture, not a continuum free-boundary
proof or a trained-network task benefit. Its three tests and raw oracle report
are archived separately.

The [non-diffusion controls](../hcsn_memory_controls/PROTOCOL.md) implement
associative overwrite retrieval, delayed copy and pair composition, with
independent clock/symbol random streams and no query-answer leakage. Their
672 generated episodes contain 48,128 events and 5,376 queries. Three semantic
tests pass; zero model-training runs are credited for this suite. A 25-feature
adapter appends four zeros and uses an explicit validity mask; it cannot reuse
the localization channel mask. Real asynchronous multimodal tasks and these
counterfactual controls still require training and independent confirmation.

## CI, reproducibility and P5

The [evidence index](evidence/p0p5-20261110/README.md) lists exact source capsules,
commands, model and data digests, independent audits, failed-attempt receipts,
cost scopes and draft evidence assets. The repository is public; large raw
assets are retained in an unpublished draft release and require appropriate
repository access. Authenticated byte readback, not a successful upload request,
is the archival check. Main has not been merged or modified by this work.
The [earlier asset index](evidence/p0p5-resource-replay-20261110/assets.json)
records 29 known payloads with retained complete authenticated readbacks:
28 previously verified payloads plus the new full-D archive. This is not a
fresh count of all release API entries. The new asset's anonymous probes
returned 404 and the release remained unpublished; old metadata-only and
failed-starter entries retain their earlier limitations.
The [later numerical publication](evidence/p0p5-terminal-numerics-20261110/publication-originals/RESULT.json)
adds two completely verified original archives, assets733215514 and733217675,
for31 known payloads with full authenticated readbacks across these indexes.
This remains a cumulative evidence count, not a fresh release API inventory.
The main numerical archive is34,050,599 bytes; its exact hash, all487 original
members and external collection finality are bound in the new appendix.

Local science tests, numerical qualifications, training adequacy, scientific
benefit and overall repository CI remain separate. The earlier hosted
science run **42890048946**, attempt 1, succeeded for source head
`cd3b7ac49294174a98e02636247615534c19bd89` and tested merge
`f63b067ac577a6eea363c37d1358f65dc7b4f4ba`. Both have tree
`4bb4995c3c1058d268c032a0d15cdfe9297a6ff8`. Its exact
[14-file artifact](evidence/p0p5-resource-replay-20261110/publication-and-science/science-run-42890048946-attempt1-artifact-13797877354.zip),
artifact 13797877354, is retained with complete hash/CRC verification. It
contains 92 science tests, four historical numerical error-budget fixtures,
the four-manifest 785-file integrity check, three QVI tests, three control
tests and source/index immutability. This success does not qualify the
training domain or any later evidence assembly.

The later retained [original artifact 13802347858](evidence/p0p5-ci-launch-closure-20261110/science-original/artifact-13802347858.zip)
belongs to science run **42899977177**, attempt 1. Its
[actual identity](evidence/p0p5-ci-launch-closure-20261110/science-original/identity.json)
records source `652263b31ebebc4e85b5b2986cb144f0127cbad2`, tested merge
`ffa6eeaa90520ccf234cb6c79828e7d859614fe5` and equal source/tested tree
`aa5cc6bc55b0dc1cb68adf62886fb9646962de03`. Complete byte/member/CRC verification
binds the 91,935-byte original ZIP. Its fixture and evidence steps pass:
six manifests, 1,053 files, 51 ZIPs and 287 relative links, zero evidence
errors. This remains a scoped CPU fixture result, separate from training
qualification and overall CI.

The [20:00 UTC CI observations](evidence/p0p5-resource-replay-20261110/ci/hcsn-ci-current-head-observation-v1.json)
and [job details](evidence/p0p5-resource-replay-20261110/ci/hcsn-ci-failure-and-current-jobs-v1.json)
supersede the earlier queued observations within their own head/time scopes.
Source PR5803's blocking run **42849616115** failed at head
`56de11a29bbbb8a9aba93e67731cdee4909b4e15`. Retained Windows logs show
filename-too-long checkout failures; the contract log shows a README
readiness-discovery-link gate failure. Other cargo-deny and Bazel jobs also
failed, but two requested job-log retrievals failed and their underlying
causes remain unestablished. Original logs and retrieval errors remain in the
[CI log archive](evidence/p0p5-resource-replay-20261110/ci/current-ci-decoded-logs-v1.zip).
These old-head failures do not establish the result of a later unobserved
head. The [later original observations and decoded logs](evidence/p0p5-ci-launch-closure-20261110/README.md)
retain the cd3b7ac4 head's failed blocking run, including the existing README
readiness-discovery gate and a spelling false positive in one immutable
Base64 receipt. Only that exact encoded receipt path was excluded from prose
spelling; the original evidence and scientific rules were unchanged. The
[same-version local red/green check](evidence/p0p5-ci-launch-closure-20261110/codespell-fix/RESULT.json)
passes on the narrow correction. The new appendix also preserves that exact
failed-lint stdout, including the five strings it complained about; this one
historical log is likewise excluded from prose spelling, with its bytes still
fixed by the manifest. No evidence directory is broadly excluded.
The new collector's exact `git-response.json` likewise contains an original
Base64 ZIP payload. Its decoded35,529 bytes match the frozen collector capsule;
one spelling finding inside that payload is excluded by its exact file path,
while the original bytes and integrity checks remain unchanged.

The [exact recovered artifact](evidence/p0p5-recovery-20261111/ci-science/ORIGINAL.zip)
for science run **42922677682**, attempt 1, binds source
`b908827abcf60b7ce22fe1b8b299206a31484550` and tested merge
`00a2b987e812636437ac6b42b3afc712c1c4207a` to equal tree
`573c6399fcc2c2b9ef4197f4f503520cde3cad51`. All its declared steps pass,
including 92 fixtures and ten-manifest evidence integrity. The new recovery
checks the same 121491-byte ZIP by its original full SHA256; it is a new
readback receipt, not the missing earlier local verifier record and not a
test rerun. The [separate blocking-CI readback](evidence/p0p5-recovery-20261111/ci-blocking/DIAGNOSIS.json)
still records failed jobs in run 42922677728, including the existing root
README discovery-link failure. Six implicated file blobs are unchanged
between the previous published source and this head. An unavailable cargo
log leaves its underlying cause unknown. These observations do not certify
this later recovery/CURRENT edit or establish repository-wide success.

At the retained later observation, source
`fdbc954bb259a709275771fe151b4f0c8d245b48` had successful science run42902660902
and canary42902660830, architecture42902660993 in progress, and blocking
run42902661147 queued. No hosted spelling pass or repository-wide all-green
result is inferred from that queue, and no old-head failure is assigned to
an unobserved future head.

The [next exact-head observation](evidence/p0p5-c2-progress-20261110/ci/observations-original.zip)
reports science run42907725860 attempt1 successful at source
`7351e1a2c60e318686d3c01372acbde149af4432`; that observation did not download its
artifact. Its blocking run42907726032 had successful spelling and blob-size
jobs, but failed contract, cargo-deny and Windows jobs. The later
[original contract log](evidence/p0p5-terminal-numerics-20261110/ci-current/ORIGINALS.zip)
identifies the README readiness-discovery failure. The
[source explanation](evidence/p0p5-terminal-numerics-20261110/ci-current/CONTRACT-EXPLANATION.json)
records an unchanged empty root README. The cargo-deny log request instead
returned a transport error; its cause is not inferred. No all-green result
or guarantee for the newly edited head follows from these historical runs.

The [committed-object closure](evidence/p0p5-resource-replay-20261110/publication/committed-current-evidence-closure-v2/RESULT.json)
verifies 794 distinct blobs at the same earlier tree, after restoring fifteen
ignored original logs that were absent from their first committed evidence
trees. The retained failure and exact repaired bytes are in the new index;
this earlier closure does not certify a future commit. The
[later committed-object proof](evidence/p0p5-ci-launch-closure-20261110/earlier-tree/committed-blobs/RESULT.json)
verifies 1,068 distinct Git blobs at local commit
`a33490f926debd60ce21f73b2ea64c1b90b8338a`, tree
`aa5cc6bc55b0dc1cb68adf62886fb9646962de03`, matching the later hosted source.
It still does not certify this newer CURRENT edit or C2 appendix.
The [subsequent committed-blob proof](evidence/p0p5-c2-progress-20261110/prior-head-checks/committed-blobs/RESULT.json)
verifies1,273 distinct files at local commit
`a143bfda5036a54ed87afe21d184b5a9749fa0ee`, whose tree
`772cbf882db520525d6fa5c805c296aa2e8b97eb` matches remote7351e1a2.
Its [local integrity record](evidence/p0p5-c2-progress-20261110/prior-head-checks/worktree/RESULT.json)
covers eight manifests,1,255 files,66 ZIPs and362 relative links with zero errors.
Those are exact earlier-tree checks, not a claim about this later appendix.

From the repository root, verify the new package and its linked status pages
using the module entry point:

```bash
python -B -m qualification.hcsn_differentiable.evidence_chain \
  --manifest qualification/hcsn_differentiable/evidence/p0p5-20261110/MANIFEST.json \
  --manifest qualification/hcsn_differentiable/evidence/p0p5-followup-20261110/MANIFEST.json \
  --manifest qualification/hcsn_differentiable/evidence/p0p5-resource-replay-20261110/MANIFEST.json \
  --manifest qualification/hcsn_differentiable/evidence/p0p5-resource-closure-20261110/MANIFEST.json \
  --manifest qualification/hcsn_differentiable/evidence/p0p5-c2-launch-20261110/MANIFEST.json \
  --manifest qualification/hcsn_differentiable/evidence/p0p5-ci-launch-closure-20261110/MANIFEST.json \
  --manifest qualification/hcsn_differentiable/evidence/p0p5-c2-progress-20261110/MANIFEST.json \
  --manifest qualification/hcsn_differentiable/evidence/p0p5-terminal-numerics-20261110/MANIFEST.json \
  --manifest qualification/hcsn_differentiable/evidence/localization-v2-20261108/MANIFEST.json \
  --manifest qualification/hcsn_differentiable/evidence/math-closure-20261108/MANIFEST.json \
  --markdown qualification/hcsn_differentiable/CURRENT.md \
  --markdown qualification/hcsn_differentiable/evidence/p0p5-resource-replay-20261110/README.md \
  --markdown qualification/hcsn_differentiable/evidence/p0p5-resource-replay-20261110/resource-analysis-v1/output-v1/REPORT.md \
  --markdown qualification/hcsn_differentiable/evidence/p0p5-c2-launch-20261110/README.md \
  --markdown qualification/hcsn_differentiable/evidence/p0p5-ci-launch-closure-20261110/README.md \
  --markdown qualification/hcsn_differentiable/evidence/p0p5-c2-progress-20261110/README.md \
  --markdown qualification/hcsn_differentiable/evidence/p0p5-terminal-numerics-20261110/README.md \
  --markdown qualification/hcsn_differentiable/evidence/p0p5-terminal-numerics-20261110/mathematical-diagnosis/NOTE.md \
  --markdown qualification/hcsn_differentiable/evidence/p0p5-terminal-numerics-20261110/local-diagnosis/fixed48/REPORT.md \
  --markdown qualification/hcsn_differentiable/evidence/p0p5-terminal-numerics-20261110/numerics-independent-review/REPORT.md \
  --output /tmp/hcsn-terminal-numerics-integrity.json
```

Choose a new result path if that output already exists. The science workflow
checks all ten historical/current manifests. Running
the Python file directly can shadow the standard-library `operator` module;
use `python -B -m` as above. Integrity validates bytes and links; it does not
grant scientific or training-domain credit.

The [API publication receipt](evidence/p0p5-20261110/publication/api-source-prs-v1.json)
binds four draft PRs to exact remote heads and complete source trees equal to
their local commits. The recovered
[original native publisher receipt](evidence/p0p5-20261110/publication/native-v8-publisher-reconciliation.json)
shows exit 1 after a 240-second remote-reference timeout before its push step.
That failed attempt is preserved; the independent API publication did not
overwrite its branch or repeat the original job.

FP32/mixed precision, fused kernels, state compression, event-sparse inference,
HCSN-plus-attention pretraining and ordinary production-entry adoption remain
gated on demonstrated real-task benefit. Exact caching above is a measured
training-enablement change; it is not evidence of energy or scaling superiority.
