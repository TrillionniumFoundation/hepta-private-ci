# Round 7 research contract

`PROTOCOL.json` records the authoritative run status and freeze binding.
No outcome, superiority claim, or production
promotion follows from this document. The source baseline is recorded in
`SOURCE_BASELINE.json`; earlier source files remain byte-identical.

## 1. Question and scope

This experiment asks whether a jointly trained stochastic-state neuron helps a
finite evidence-gathering controller, and whether changing its event law helps
after controlling for the controller's planning horizon. It separates a
terminal Gaussian threshold, a first-passage approximation, and the benefit of
multi-step control. It does not rename an ordinary probit activation and claim a
new function class.

The software is an isolated research profile. It neither replaces the main
Hepta `sparse_tick` contract nor establishes a production migration, native
implementation of the new dynamics, continuous QVI solution, or a theorem from
arXiv:2606.16846. A finite task DP is a numerical reference for this declared
task only. A positive result on this task would need replication on additional
tasks before a general architecture claim.

## 2. Three laws with a shared parameterization

Within each tick, the public-content encoder supplies a frozen drive `u`. The
continuous reference equation is

\[
 dX_t=(u-\kappa X_t)dt+\sigma dW_t.
\]

`EventDynamics` stores a probability row vector on an odd grid of `N` interior
voltage states and two refractory states. It uses FP64. Parameters are smooth,
bounded transforms: `0 < leak < 2`, `0.05 < diffusion < 0.8`,
`0.35 < boundary < 2`, reset centers strictly within `0.75 * boundary`, and
`0.05 < recovery_probability < 0.95`. The reset standard deviation is fixed at
`0.08 * boundary`. The initial mass is exactly at zero voltage. A trainable
reset is a categorical projection of a smooth reset distribution, not a
straight-through gradient for a deterministic reset point.

| Mode | One-tick transition | What is exact | What is approximated |
| --- | --- | --- | --- |
| `continuous` | Exact affine OU endpoint Gaussian projected onto the interior grid; tails fold into extreme bins | Gaussian moments for the frozen drive | Repeated projection; this is a finite-state distribution baseline, not an unrestricted continuous latent process |
| `clocked` | Endpoint Gaussian interior bins and mass outside `[-b,b]`; outside mass emits a signed event at the tick end | One-step endpoint probabilities for each source grid point | Grid projection and discrete endpoint event/reset times; crossings followed by a return inside the interval are not events |
| `first_passage` | Matrix exponential of an absorbing upwind finite-difference CTMC generator | First absorption of the stated finite-state CTMC, subject to floating-point error | Approximation to continuous OU first passage, spatial numerical diffusion, and discrete post-event/refractory handling |

For the CTMC, `h=2b/(N+1)`, diffusion rate is `sigma^2/(2h^2)`, and right/left
jump rates add `max(drift,0)/h` and `max(-drift,0)/h`, respectively. Generator
rows sum to zero. This is not an analytic two-barrier OU first-passage formula.
Grid-convergence evidence is required; agreement between two matrix-exponential
implementations alone does not establish continuum accuracy.

The upwind CTMC's local variance rate is `sigma^2 + abs(drift) * h`, rather
than `sigma^2`. When diffusion is small relative to drift and mesh spacing,
this extra variance can dominate first-passage probabilities. A zero-drift
Brownian convergence test does not certify the low-noise, nonzero-drift regime.
This fixed-grid experiment is evidence about the declared finite-state laws;
it cannot attribute a coarse-grid advantage to the continuous OU mechanism.
Likewise, reducing `dt` at fixed endpoint-projection grid can freeze its
projected dynamics, and fixed `q` changes physical recovery time with `dt`.
Hold both grid and tick duration fixed in primary comparisons and disclose
these approximation limits.

An absorbed path moves to the corresponding refractory state and is frozen for
the remainder of that tick. A path already refractory at tick start can be
released with probability `q` only at tick end and cannot fire during that tick.
Its next voltage is sampled from the declared reset distribution. Consequently
there is at most one event per path per tick, at least a full tick without firing
after an event, and repeated firing across ticks. No sub-tick event time is
exported. Sub-tick latency or asynchronous speedups must not be inferred.

`continuous` never reaches refractory states from its initial condition; reset
and recovery parameters are therefore inactive in its reachable transition law.
Report effective parameter counts and computation separately from stored counts.
The joint auxiliary regressions nevertheless include unreachable refractory
slots without occupancy weighting. Reset centers enter those slots' moment
features, so they can receive auxiliary gradients and affect shared readout
training. They are not globally inactive training parameters. Recovery does
not enter the readout moments.

## 3. Probability, event, and parity types

Terminal complementary binary probabilities at one common threshold satisfy
`p_call + p_put = 1` when the equality/atom convention is shared. With two
thresholds, the neutral interval has its own probability. Two independent
Bernoulli draws do not implement a categorical partition.

First passage at upper and lower boundaries obeys
`F_plus(t) + F_minus(t) + S(t) = 1` for the same stopping problem. In general
`F_plus(t) + F_minus(t) != 1`. `event[:, 0:2]` is the expected signed event count
for the current tick. Existing refractory mass is not a new event. Expected
counts may exceed one only after summing ticks. These event counts are not
discounted option prices, NDU action values, behavior propensities, or signed
quantized communication deltas from earlier rounds.

## 4. Public task and private fixture

The task has a hidden truth in `{-1,+1}`, ordinary noisy votes, and a delayed
source which may arrive corrupted. Conditional on truth, source votes are
independent. The corrupted flag is independent of truth and votes. `READ`
reveals the next ordinary source, `WAIT` advances time, `REPAIR` reveals the
same previously generated delayed vote, and `STOP` commits the current Bayes
answer. Repair never resamples the evidence.

Every action, including STOP, takes one tick and incurs its declared latency and
action cost. STOP commits its answer from the pre-action public belief; evidence
that would arrive during that STOP tick is not observed before commitment.
Every non-STOP action must leave a final STOP tick. Budget is debited only for
READ and REPAIR. An unavailable requested action falls back to STOP and incurs
a real failed-attempt charge. The log retains requested and executed actions.

Terminal quality is `+1` for a correct answer and `-1` for an incorrect answer.
Trajectory task utility is terminal quality minus all declared task costs.
Accumulated costs are sunk when evaluating future-state Q; they are not charged
twice. Wall time is a separate resource measure and is not silently converted
to task utility.

Only `State`, its 18 public features, legal actions, and declared task parameters
may reach an encoder, policy, or task oracle. `Episode` contains the realized
truth, unread votes, corruption flag, and seed; these stay within the environment
and evaluation logger. Identical public information is available to all arms.
The posterior feature already performs the declared Bayesian evidence update;
this is not a benchmark of learning perception from raw observations.

## 5. Teachers, training stages, and controlled-network value

The independently written task oracle enumerates conditional future evidence
from the public belief. It does not call `task.step`, read an `Episode`, or use
future fixture facts. It gives Q* for the finite task and Q1 for a requested
action followed immediately by STOP. It knows the declared task model. This
task-only oracle does not solve the stochastic neural-state control problem.

The first training stage sums each latent state's squared prediction error
against public-state teacher Q, weighted by that state's propagated mass. Both
heads are learned together with the content encoder and active neuron
parameters. This is an exact finite sum for the implemented mass-weighted
supervised objective, not a straight-through sampled-spike gradient. Its drive
uses the current public input; its public-prefix trajectories come from a fixed
exploration policy. This first stage does not differentiate through its own
selected task-action histories.

The second stage enumerates a finite DAG of public evidence states jointly with
the internal Markov states. Its Bellman order is incoming neuron transition,
state-dependent soft action, task reward and public transition, then next
joint-state value. The return component differentiates the exact expectation
for this finite graph and policy, including future reset/recovery and actions.
It uses the known model of the eight training parameter presets, not private
realized episode facts. This is stronger information than sampled model-free
reinforcement learning and must be reported as such.

The graph covers all reachable public states in its eight nominal parameter
presets. Independent nominal confirmation episodes supply new random paths and
unbiased policy-utility measurements under that model; they are not a holdout
of unseen public states or an unknown transition model. The separately frozen
parameter-stress regimes test transfer beyond those training presets.

The refinement objective is negative expected soft-policy return plus critic
and myopic auxiliary terms, with their weights fixed in `PROTOCOL.json`. Both
auxiliary targets are detached, so their updates are Bellman semi-gradients;
the exact-return-gradient claim applies to the return component. The revised
joint myopic target includes current compute cost and, if continuing, the
future immediate STOP's compute and expected event costs. The full target
includes the same costs along the complete future policy. The initial task-only
pretraining targets omit these neural costs, a deliberate two-stage distinction.

`compute_price` and `event_price` are registered utility coefficients, not
measured dollars, runtime, or energy. Report original task utility, the
additionally penalized control objective, and measured resource costs
separately. The full head starts from Q* regression and is refined toward the
current soft policy's joint value. Calling it a Q* head after refinement names
its initial teacher, not an exact optimal-value guarantee.

The readout receives raw public features as well as learned content and internal
state features. It can learn to ignore the neuron. Nonzero gradients or
parameter changes establish joint trainability, not that the event/reset
mechanism improves deployment. STOP's final answer is still the exact Bayes
rule of the task, so learned content here means a public control-feature
encoder rather than raw document perception or answer generation.

Primary deployment samples a categorical internal state, then greedily selects
a legal action from that state's chosen head. The training policy instead uses
soft actions at temperature 0.12. The finite joint DP can separately evaluate
either of these policies for its declared task configurations. Its soft-policy
value is not the greedy policy's value. A hard-state/soft-action rollout audit
validates the policy actually optimized, while hard-greedy confirmation measures
the registered deployed policy. Mean-mass and Q24 counterparts are separate
controls; Jensen's inequality prevents silently identifying their policies or
values with the sampled-state model.

A same-prefix audit must distinguish the original task oracle, the learned
estimates, exact joint-policy values where available, and sampled conditional
Qpi. Conditional rollouts resample hidden truth from the public posterior,
preserve observed evidence, and propagate the actual internal state. They do
not hold the private fixture's realized truth fixed and call that a conditional
value. The audit uses its own frozen continuation namespace.

## 6. Factorial comparison and controls

| Arm | Dynamics | Head used at deployment |
| --- | --- | --- |
| A | Clocked endpoint Gaussian/probit | Learned Q1 |
| B | Same clocked checkpoint as A | Q*-pretrained, control-refined full head |
| C | Finite-grid first passage | Learned Q1 |
| D | Same first-passage checkpoint as C | Q*-pretrained, control-refined full head |

The registered primary contrasts are B minus A (controller effect in clocked
dynamics), D minus B (event-law effect under the full head), and
`(D-C)-(B-A)` (interaction). A/B and C/D share model checkpoints; they are paired
deployments, not four independent model fits. Data, encoder/readout design,
training schedule, hard-deployment rule, and task action guard are held common
where declared. Computational work may still differ and must be measured.

The full head directly participates in return refinement, while the myopic head
has an auxiliary one-step objective and shares the full head's optimized core.
B minus A therefore measures this declared controller-and-training package;
it does not isolate planning horizon as the sole causal change. The same
qualification applies to the interaction. A separately matched optimization
experiment would be needed for that stronger causal claim.

The direct-Q control freezes core/drive parameters and zeros latent features.
It shares the public-content encoder/readout architecture but has fewer active
parameters. Its current implementation still repeats the identical readout
over latent-state slots; report this overhead rather than treating its measured
time as the minimum cost of a direct-Q predictor. The diagnostic noise group is
a subset of the dynamics group, so their gradient norms/counts are not additive.

Parameter-freeze ablations measure total contributions of those parameters to
this model. Reset centers affect both actual reset transitions and the readout's
refractory-state moment features. Boundary affects the grid, threshold, and
state features. Those ablations do not isolate one physical pathway while
holding every representation pathway fixed.

All current arms still encode dense public features and compute readouts each
tick. Events do not skip those computations or implement a sparse communication
runtime. Fewer event counts alone cannot establish lower energy or execution
cost; only the measured complete execution supports a resource comparison.

Controls include projected continuous dynamics, the explicitly identified
Gaussian/probit endpoint model, direct public-feature Q prediction, exact task
DP, and declared quantization/hard-state variants. The clocked model is the
ordinary Gaussian/probit baseline; it is not the historical native Hepta neuron
under a different name. No extra control may be promoted to a primary favorable
comparison after confirmation results are inspected.

An additional event-temperature control freezes diffusion at its initial value
and learns one scalar temperature for the event-versus-survival log odds. This
keeps the trainable count at 823 (824 stored parameters), the same as the base
FPT model. Conditional surviving-state and event-direction distributions and
recovery rows are retained. The temperature is initially one and has range
`0.25 < T < 2`. It has the same training schedule, and is secondary only.
This reweighted tick transition is a distinct discrete kernel; it is not the
original CTMC first-passage semigroup and its temperature is not physical
diffusion. Exact probability-boundary and row-mass behavior require explicit
validation. Matched parameter count is not a claim that the two function
families or measured compute costs are equal.

## 7. Artifacts, broker, and native bridge

Research file operations use an explicit broker/guard with scoped paths and
readback verification. Log artifact bytes/digests, request and execution status,
fallbacks, retries, and costs. Failed and denied attempts remain evidence. A
successful simulated label or an in-memory artifact does not establish an
actual filesystem or native execution. The broker is an interface separation,
not an operating-system sandbox against arbitrary code with filesystem access.
It materializes fixed-size source files, reveals only permitted observations,
and writes terminal outputs with server and independent client readback. This
is an artifact-backed evidence task, not evidence of open-domain software repair
or a production tool integration.

The reused native executable has SHA256
`b519cae26325f818d9596aab34504490a0b5355b9eb633369878e6f07a50e179`.
Its old build receipt and a new restoration receipt distinguish its historical
build from this run. New calls and artifact readback can establish an actual
bridge to that historical native adapter. They do not establish a native
implementation of Round7 dynamics, retraining of the main sparse kernel, or
production admission. The complete evidence bundle can include the exact
historical executable and original receipts for offline replay; this packaging
does not make it a fresh build. Publish the new execution evidence separately
from its historical compilation provenance.

The historical typed request writes its own persistent journal. Each later
`pair` request initializes a separate sparse state in a scalar-feedback
profile, and the reset comparison acts inside that two-tick pair. The pair does
not restore or update the typed request's checkpoint. The audit therefore
establishes typed-runtime execution plus artifact-linked independent kernel
feedback, not a feedback update to the same persistent typed owner.

## 8. Freeze, failures, and interpretation

`PROTOCOL.json` must be frozen with code/config/checkpoint hashes before
confirmation generation or inspection. Development speed smoke tests and
mathematical checks are recorded separately. Training choices may use only
train/dev data. All five fit seeds, all registered arms, failures, and resource
costs remain in the report. A failed attempt is not silently replaced by a new
seed. Any later scientific change requires a new version and fresh confirmation
namespace, with the earlier outcome retained.

Primary inference uses paired whole trajectories with fit seeds treated as
clusters. Multiple neural draws or repeated timesteps are not extra independent
model fits. With five fits, uncertainty about retraining is weakly estimated;
bootstrap intervals are empirical summaries, not a guarantee of coverage.
Family-wise multiplicity and practical effect thresholds are fixed in the
protocol. Non-significance, negative transfer, deployment gaps, and increased
resource costs are valid results. Implementation success and scientific
superiority are separate findings.
