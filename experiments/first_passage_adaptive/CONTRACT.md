# Adaptive first-passage experiment contract

This is a new, small synthetic study. Its scientific parent is
`71b4305c6619ed9faff98062f0ff7f932f4abfd0` on
`research/first-passage-operator-20261029`. Neither predecessor package nor its
frozen files are modified. `ADAPTIVE_PROTOCOL.json` specifies the registration.

Protocol amendment `v1a` binds the threshold implementation before its training
and before any confirmation. It preserves the earlier protocol hash and leaves
the physical/meta numerical settings unchanged. It also clarifies the existing
SG sign convention: the update derivative is `-feature * d(probability)/d(distance)`.

## Baseline evidence

At the pinned remote commit, `first_passage_operator/SOURCE_FREEZE.json` and the
network freeze/development/diagnostic records say `confirmation_opened=false`.
No operator confirmation result was read in that remote tree. This observation
does not certify that no unpublished run exists. Earlier conversational claims
of six failed confirmation comparisons are not manufactured into evidence.

`first_passage_cell/RESULTS.md` reports three passed comparisons for voluntary
maintenance/reset policies. It explicitly separates those findings from a
jointly optimized natural firing barrier, general network training and
production owner activation. The operator's later development results are
task dependent: first-passage BCE is about 0.554 on order and 0.692 on delayed
match, compared with about 0.00694 and 0.404 for its registered RNN. These are
development observations, not substitutes for confirmation.

## One active contract and its three outcomes

Use a constant-drift free voltage, strictly below its barrier:

    dX = mu dt + sigma dW,  distance = barrier - X_0 > 0.

Let `tau_hit` be its first barrier hit and `tau_cancel` an independent exponential
time of rate `cancel_rate >= 0`. For positive horizon `T`, the mutually exclusive
outcomes, in API order, are:

1. `hit`: first passage occurs by `T` and before cancellation.
2. `survive`: neither event occurs by `T`.
3. `cancel`: cancellation occurs by `T` and before first passage.

The probabilities are `H_lambda(T)`, `exp(-lambda*T)*S(T)`, and their remaining
mass. Cancellation is independently integrated when subtraction is ill
conditioned. It is an observed event, not a missing observation or a resource
price. `survive` includes actual survival evidence to `T`; a missing observation
must not be relabelled as survival.

`outcome_law(distance, mu, sigma, cancel_rate, horizon, derivatives=2)` returns
`OutcomeLaw(probability, jacobian, hessian, quadrature_error)`. Derivative columns
are `(distance, mu, sigma, cancel_rate)`. The probability vector sums to one;
the summed Jacobian and Hessian are zero. All inputs must be finite, with
positive distance, diffusion and horizon, and nonnegative cancellation.

Closed first-passage probabilities and analytic density-score integrands are
used. Numerical integration still has an error estimate and a validated domain;
this is not a universal floating-point error theorem. A requested derivative
order of zero returns uncomputed zero arrays and must not be interpreted as a
zero mathematical derivative. An initially hit state, refractory holding,
reset, repeated contracts and remaining time require separate state-machine
branches. This single-contract kernel does not silently approximate them.

## Physical task gradients

For fixed conditional task costs `c`, the objective is

    L(theta) = sum_j p_j(theta) c_j = E[c(hard_outcome)].

It is not a loss evaluated at the mean output. If conditional costs themselves
depend on parameters, their derivatives must be included by the caller.

The physical-training fixture updates a shared drift bias, diffusion and
physical cancellation rate through this actual objective. There is no readout
whose training could substitute for training these coefficients. Parameter
movement, task-only derivatives and independent perturbations are reported.
Projection keeps parameters in the registered domain. Training decrease is a
property of the checked updates, not a proof of global optimization or that an
environment's uncontrolled physical parameters can be changed by a policy.

## Biased gradients and genuine meta-gradients

The meta fixture has fixed physical dynamics. Its separate shape parameters
only define the surrogate derivative used by an inner learning rule. Updating
shape parameters is learning an optimizer; it is not fitting the physical law.

All arms use the same physical categorical outcome law and hard conditional
loss. The exact baseline differentiates its expected hard loss. Fixed SG and
meta-SG instead update from hard one-hot outcomes using a declared surrogate.
The three inner steps produce 27 possible trajectories. Their outer objective
is evaluated by enumerating all leaves with their physical path probabilities.

Because inner parameters change the later outcome distribution, the full
hypergradient includes both the derivative of each path's probability and the
derivative through its inner updates. Holding path probabilities fixed is a
different, generally biased hypergradient. Neither a local probability
derivative nor a useful SG is automatically the derivative of a deep hard
network's expected loss.

The exact, fixed-SG and meta-SG outer objectives are reported together. This
three-example known-law fixture supports a transparent derivative comparison;
it has no broad superiority or sampling-convergence claim. The exact learner
uses deterministic expected-loss updates while SG/meta-SG enumerate stochastic
updates; sharing the physical law and three updates does not give equal oracle
cost. All kernel evaluations are counted.

## Boundaries, costs and owner execution

The boundary comparison is separate from gradient identification. Fixed,
ordinary context-conditioned and value-derived thresholds receive the same
public state, law, cost, remaining time, resource budget and legal actions.
The ordinary control must actually use those contexts. Actual parameter counts
and search costs are reported without unused parameter padding.

The registered family uses one constant threshold per episode, reset voltage
zero, positive drift/diffusion, and an integer hit budget K. Each actual hit
pays `b-cost`; it resets and starts a positive refractory interval. Global
physical cancellation remains active during refractory holding. With
`q=discount+cancel_rate`, the analytic calibration objective is

    J(b) = (b-cost) sum(n=1..K) exp[-q*(n-1)*d]
           * H_q(T-(n-1)*d, n*b).

Terms with nonpositive remaining time vanish. STOP has zero value. This is the
value of the constant-threshold family, not the optimal arbitrary history-
dependent controller. Actual returns use actual event times and discount only;
the cancellation probability is realized by the event clock, not charged twice.

The fixed and value policies use a 257-point grid, bounded refinement at every
interior grid peak, endpoints and STOP. This numerical search does not certify
a global optimum. The ordinary policy uses training-standardized quadratic
features of all eight public inputs and `b=cost+(4-cost)*sigmoid(features*w)`.
Its three registered initial intercepts are -2, -1 and 0; other weights start
at zero. L-BFGS-B has at most 160 iterations, fixed tolerances and nonintercept
ridge 1e-5. Development chooses only among those three fitted candidates.
The protocol binds all numerical settings, and every candidate's cost and
convergence status is retained. Constant discount columns do not count as
active fitted capacity. The same costs and feasible actions are public to all
arms; their controller classes and computational budgets are explicitly unequal.

Three predeclared strata vary nominal conditions, cost and deadline. Each fit
seed has 128 training, 64 development and 256 confirmation contexts. Each
confirmation context has 64 paired rollouts. The context is the resampling unit;
repeats are never independent samples. Eight predeclared intervals (two pooled
contrasts plus six stratum contrasts) use two-sided Bonferroni family alpha
0.05. Bootstrap sampling stays within each fit-seed/stratum cell. Pooled effects
weight strata and fitted seeds equally. Passing both pooled lower bounds above
0.005 with positive effects in every fit seed supports the narrow primary
claim. A claim covering all three strata additionally requires all six stratum
lower bounds above 0.005. These are empirical intervals conditional on the
frozen fits, not a guarantee over future training seeds or tasks.

A resource price has units of utility per resource and is separate from
`cancel_rate`, which has units of inverse time. Resource claims use actual
post-guard costs. A requested action, predicted utility or native arithmetic
receipt alone is not evidence of execution or an Organ Credit feedback loop.

Native validation binds the owner source, binary and receipt semantics. It
checks that forecasts are consumed consistently and observed costs/returns are
accounted for. An executable research adapter does not confer production
authority or a safety certificate.

## Frozen confirmation and reporting

New train, meta-train, development and confirmation streams are disjoint.
The protocol, context generators, models, threshold settings and evaluator
must be source-bound before a one-shot confirmation. The threshold runner must
also bind its context distributions, sample counts and complete search budget.
Training or threshold selection may not read confirmation data.

Physical and meta studies use their final registered updates. All backtracking,
model searches, probability/derivative calls and native calls count as work.
Equal inner-update budgets do not imply equal computation or equal wall time.

The registered threshold advantage gate is distinct from numerical correctness
and requires executed net utility. All negative, inconclusive and failed
outcomes remain visible. A changed scientific method requires a new study and
fresh confirmation; it does not overwrite this study or its parent.
