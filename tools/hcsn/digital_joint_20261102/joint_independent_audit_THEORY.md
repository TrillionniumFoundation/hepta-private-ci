# Independent audit: attainable claims and acceptance boundaries

This note states mathematical constraints before the new experiment is frozen.
It does not select a model, inspect a new confirmation result, or establish a
benefit for an analytic cell. The archived task implementation is
`digital_read_before_20261031/task.py` at commit
`012bcf3505cb9306d9cef094a1acc3ca34c978be`.

## 1. The correct-law Bayes value is an upper bound

Let the allowed information history at decision time t contain the declared
public schedule and fees, all previous actions, completed read outcomes and
failures, and the task resource state. It excludes unread packet contents,
evaluator labels, and reconstructing hidden outcomes from generator seeds,
world identifiers, or verification digests. The declared law assumes that
public schedules are exogenous; read outcomes are conditionally independent
given the hidden binary label and source reliability, with a fixed decoder
confusion matrix; and read failures follow the declared exogenous failure law.

Under a **correct, known** law M, let p be the label posterior. Then
`(tick, budget, pending source/due time, broken, p, public schedule)` is a
sufficient state for future task rewards and charges. Already paid charges are
sunk and do not enter the continuation optimization. The terminal values are
`0`, `1-2p`, `2p-1`. For each continuing action, the value is its negative new
fee plus the conditional expectation of the optimal successor value. Backward
induction at the finite deadline therefore gives the optimal task value V_M*.

Consider any cell state Z constructed causally from this history and an
internal random source independent of the environment. A full-history policy
can simulate the same cell updates, random draws, and action rule. Thus this
cell policy is already in the policy class optimized by the correct-law
Bellman recursion. Equivalently, at each history its randomized action value
is a convex combination of legal Q values, no greater than their maximum.
Consequently

\[
  V_M(\pi_{\rm cell}) \leq V_M^*.
\]

This holds for arbitrary nonlinear cells, continuous or discretized dynamics,
distribution-valued states, and randomized controllers. A larger retained state
can lose less information than another compressed learner; it does not create
information beyond the allowed complete history. In a new dynamic-hidden-state
task, the same argument applies after replacing scalar p by the full filtering
posterior and using the correct controlled transition law.

This is an expectation statement under the declared law, not an inequality
between noisy sample means on a finite confirmation cohort. It also does not
cover a different observation interface: if raw decoder logits or packet
features are newly exposed to the cell, the Bayes baseline must receive those
same observations and use their appropriate likelihoods.

The Bellman objective above includes declared task charges. It does **not**
include host CPU, memory, hardware energy, or amortized training/planning costs.
A cheaper approximate policy can improve a separately declared computational
objective even while its task value is below V_M*. That is an attainable
adoption question; exceeding the correct-law task optimum is not.

## 2. Fitted-law optimality is different from real-law optimality

The archived reference estimates its confusion matrix from 64 balanced TRAIN
calibration packets. Each row has 32 observations and uses
`(counts + .5)/(32 + 1)`. It optimizes the fitted law Mhat. Its value under the
actual generator/decoder law M need not be optimal.

A concrete counterexample uses allowed archived OOD parameter levels. Take
six slots with duration 1.5, reliability .55, read delay 1, first READ price
.01 and all remaining READ prices .18; latency price .04, failure probability
.16, and REPAIR price .05. Suppose the true symmetric decoder accuracy is .85,
but the balanced calibration happens to contain 31 correct answers out of 32
in each row. The fitted accuracy is then 31.5/33 = 21/22. This calibration event
has positive probability, approximately .000969295 under the stipulated true
independent decoder law.

The first READ costs .01 + .04(1.5) = .07. A successful read followed by its
best immediate submission, with STOP on failure, has expected value

\[
 (1-.16)(2(.55)-1)(2q-1)-.07.
\]

It is +.006363636 under q=21/22 but -.0112 under q=.85. The full archived
`task.Oracle` recursion selects that READ under the fitted law and STOP under
the true law; subsequent expensive reads do not change this conclusion. The
ordinary same-information STOP policy has true value zero, beating the fitted
DP policy by .0112 without an analytic cell or an extra observation. These are
counterexample parameters, **not measured FullHX error rates**.

Therefore beating a fitted-law DP reference can indicate model-estimation or
misspecification effects; it is not by itself an independent core advantage.
Conversely, failure to beat it does not prove a core has zero effect.

More generally, if every admissible policy has
`|V_M(pi)-V_Mhat(pi)| <= epsilon`, fitted-law optimality implies true-law regret
at most `2*epsilon`, by adding and subtracting the two fitted values. Such a
uniform error bound must be proved or estimated separately; the calibration
point estimate alone does not provide it.

## 3. Gates that preserve a strong comparison

| Claim | Required comparison and evidence |
| --- | --- |
| Finite CTMC operator correctness | Nonnegative off-diagonal rates, zero row sums, full `exp(dt Q)` propagation; mass, semigroup, complete successor/reset and all active-parameter gradient checks. |
| Continuous Brownian approximation | Same physical law and reset/boundary convention across grid refinements; independent continuous reference; state/function/event observables with declared mesh and time errors. A finite-exponential gradient is not automatically a continuum derivative. |
| Learned core increment | Same available observations, teacher access, fitting data and declared resource budget; strong ordinary/SSM/GRU or full-Markov models; fixed/value 2x2 retained; compare D-B on fresh frozen confirmation. Include a correctly informed Bayes reference as an upper-bound diagnostic. |
| Adoption under compute constraints | Strongest feasible same-budget baseline, including sufficient-statistic log-odds/filtering and cached or compiled finite DP; quality noninferiority and an explicit CPU/latency/memory or net-utility gain. No claim based on a deliberately repeated naive DP implementation. |
| Broader architecture benefit | Multiple generators and misspecification regimes, including cases outside the candidate's built-in physical family; identify this new experiment separately from the archived static-label failure. |

The CPU contract must be fixed before fitting and enforced per fit, with
collection, teacher labels, optimization, export, table construction and failed
attempts recorded. Any training-cost amortization requires a predeclared reuse
count. Inference must include loading, filtering/cell propagation, controller,
actual READ attempts and successful decodes, and required persistence. Measured
CPU and logical task-time fees remain distinct. A net objective must fix its
conversion prices before confirmation; prices cannot be selected afterward to
favor an arm.

## 4. Parameter and mesh cautions for the proposed CTMC

For normalized grid spacing h and physical boundary b, the proposed centered
rates are

\[
 q_\pm=\frac{\sigma^2}{2b^2h^2}\pm\frac{\mu}{2bh},
 \qquad \mu=\mathrm{bias}+\mathrm{gain}\,s(2r-1).
\]

They require `sigma^2 >= |mu|*b*h`; positivity must be verified over the whole
declared envelope rather than repaired by clamping. Grid-refinement comparisons
must preserve physical parameters and normalize observables consistently.

With reset center and reset standard deviation proportional to b, the
normalized reset distribution depends on reset-center/b and reset-sd/b, not b separately.
Moreover, scaling `(b, sigma, gain, bias, reset centers)` by a common positive
factor leaves the normalized generator unchanged whenever the scaled parameters
remain inside the declared envelope. If emissions and costs are also normalized,
this is a scale gauge: the current eight raw coordinates, including learned
normalized reset standard deviation, identify at most seven independent
effects across informative drive contexts. The earlier seven-coordinate version
with fixed normalized reset standard deviation similarly had at most six.
A trainable global b is not a time-varying boundary or a solved
continuous free-boundary problem. Fix a gauge for task training, or explicitly
report the redundancy and its null sensitivity.

The proposed signed `gain=.9*tanh(raw_gain)` is a new parameterization and must
be frozen as such. If all task contexts use symbol=0 or reliability=.5, gain is
inactive regardless of its formal parameter count. Gradient qualification must
include informative contexts; training capacity counts must exclude coordinates
that the task never uses. Full unconstrained-Markov baselines likewise need
their row-sum constraints, regularization, initial model knowledge and effective
coordinates declared.

## 5. Interpretation of the new dynamic-task comparison

The current implementation is a new completion-current sensing task whose
target is the sign at deadline six. Its supervisor uses a supplied finite CTMC
law plus TRAIN-fitted decoder confusion and supplies posterior mass, forecast
bank and DP labels. Those are training targets, not policy inputs. Results
would concern supervised learning within this model family; they would not
establish identification of an unknown real-world physical law.

Both the structured renewal model and the unrestricted full-Markov model retain
the complete 33-state distribution and propagate it by matrix exponentials.
Their comparison therefore tests generator parameter structure/inductive bias
and its computational consequences. It does not isolate analytic propagation
against nonanalytic propagation, or prove that events/reset alone are the causal
source of a gain. The GRU comparison addresses an additional architecture.

The engineering pilot has only drives -1/+1 in TRAIN and adds drive zero in OOD.
An unrestricted model with three independent Q matrices receives no TRAIN
gradient for its Q0, while the structured law shares rates/reset parameters
across drives. A formal comparison should cover all three drives in TRAIN or
include a comparably input-conditioned/shared unrestricted generator. Otherwise
an OOD advantage remains confounded by unseen-drive parameter sharing. This
issue is identified before formal fitting or confirmation, not selected from
an outcome. Different duration/reliability/fee regimes can still form declared
stress domains after this baseline defect is removed.

The final formal protocol reviewed after this note addresses that defect in
both ways: TRAIN covers -1/0/+1, and an additional affine-Markov baseline learns
two unrestricted endpoint generators with Q0=(Qminus+Qplus)/2. All four families
are retained. The independent actual-loss audit covers all four models, eight
physical raw coordinates, GRU gates/decoders, and feasible boundary derivatives
of both unrestricted generator parameterizations.

The formal secondary adoption family measures complete request execution under
matched fitting CPU admission. It has not yet defined a deployment reuse count
for adding the actual training-cost difference to every request. Accordingly,
that gate can establish a conditional inference frontier, not full-lifecycle
net cost or hardware energy adoption. The actual fitting and supervisory costs
remain separate measured quantities.

## 6. CPU-clock failure and admission authority

The first formal attempt's fit23 renewal worker terminated with SIGXCPU. Its
expected RLIMIT soft setting was `ceil(61.2 - 6.250056) = 55`, while final wait4
reported only 51.424929 worker CPU seconds and the last /proc sample was 51.38.
Thus integer ceiling alone does not explain the discrepancy. Other initial
workers with the same soft setting completed normally; none of these outputs
can be substituted into a repaired-source confirmation.

Linux distinguishes the profiling CPU clock used for RLIMIT accounting from
the scheduler-runtime CPU clock used by CLOCK_PROCESS_CPUTIME_ID. Its source
also has adjusted user/system accounting for process resource reporting. See
the primary implementations in
[posix-cpu-timers.c](https://github.com/torvalds/linux/blob/v6.18/kernel/time/posix-cpu-timers.c)
and [kernel/sys.c](https://github.com/torvalds/linux/blob/v6.18/kernel/sys.c).
These implementations explain why equality of all those clocks must not be
assumed; they do not establish the exact configuration or full cause on this
particular host.

An isolated short local probe set soft=2/hard=3. At SIGXCPU it measured
PROF=2.003594193, SCHED/process_time=1.975508204 and getrusage=1.975508 seconds.
The complete worker source and output are retained as
`joint_independent_audit_cpuclock_worker.py` and
`joint_independent_audit_cpuclock_probe.json`. This proves a local clock
discrepancy, not an explanation of the entire formal-fit discrepancy.

A revised RLIMIT may be a separately declared generous disaster backstop. The
scientific 60-second standalone budget, 2% tolerance, observed CPU matching,
cooperative work deadline and final wait4 admission must remain unchanged.
Repair requires a new source identity and the complete affected fitting stage
to restart; the earlier successful weights cannot be selected around the
failed worker. A wider backstop alone is not a passed scientific CPU gate.

The interrupted training worker kept its optimizer-step and feedback-round
arrays in memory until final export. Accordingly, its unflushed step-level
trace is unavailable after SIGXCPU. Preserved evidence comprises its source,
inputs, STARTED metadata, process logs and CPU/exit receipt; it must not be
described as a complete durable record of every interrupted optimization step.
