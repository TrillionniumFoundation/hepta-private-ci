# Adaptive first-passage gradients and Hepta execution

This package completes a reproducible research implementation of the
one-touch event operator, physical-parameter training, complete stochastic
meta-gradients, a same-information threshold experiment, and native Hepta
execution with resource-price feedback. The scientific baseline is
`71b4305c6619ed9faff98062f0ff7f932f4abfd0`. Both predecessor packages remain
unchanged. This is a research result, not production TaskFlow activation.

The protocol was committed before confirmation. The two source/model freezes
were committed in `99f4d90ce4bb773240840f10cf65e28c72a4092e` before either
confirmation stream was opened. Negative results, superseded pre-confirmation
runs and their costs are retained.

## Results

### True physical gradients and complete meta-gradients

The physical fixture has three observed outcomes: hit, survive and cancel.
It trains the true expected hard-outcome loss, with no trainable readout.

| Quantity | Initial | Trained |
| --- | ---: | ---: |
| Drift bias mu | 0.2 | 0.650046003 |
| Diffusion sigma | 0.8 | 0.2 |
| Physical cancellation rate | 0.4 | 0 |
| Training expected loss | 0.366104015 | 0.000599156 |
| Development expected loss | 0.439421278 | 0.014260405 |
| Confirmation expected loss | 0.401659274 | 0.011961764 |

Sigma and cancellation reach their registered lower bounds. This task favors
low noise and no cancellation; it does not establish that learning a positive
cancellation rate automatically reduces energy or implements Organ Credit.

The SG experiment holds physical dynamics fixed and learns optimizer shape.
Its three hard inner updates have 27 possible outcome paths. The outer
derivative includes both parameter propagation and the changing path
probabilities. Whole-objective finite differences agree to about 1.03e-9 for
physical training and 8.34e-12 for the complete meta-gradient. Independent
reviews also check the zero-drift/zero-cancellation corner and all Hessian
entries. Derivatives use analytic score integrands with numerical quadrature;
they are not asserted to be symbolically exact floating-point quantities.

| Confirmation learner | Expected hard loss, lower is better |
| --- | ---: |
| True expected-gradient inner baseline | 0.286581918 |
| Fixed surrogate | 0.340256280 |
| Learned meta-surrogate | 0.337455942 |

Meta-learning improves this fixed surrogate but remains worse than the true
expected-gradient baseline. The physical parameters and optimizer shape are
different parameter families. This finite tree is not an unbiased gradient
implementation for an arbitrary multilayer hard-spiking network.

### Finite deadline and resource budget

Three fitted seeds each use 128 training, 64 development and 256 confirmation
contexts. Confirmation includes 768 independent context clusters and 64
paired rollouts per context, hence 49,152 executions per arm. The ordinary
controller consumes the same eight public inputs as the value planner and
has 45 stored coefficients, 36 active coefficients. Its three initializations
and all optimization costs are retained.

| Controller | Registered equally weighted executed utility |
| --- | ---: |
| Fixed threshold | 0.641497818 |
| Ordinary context threshold | 0.764857494 |
| Value threshold | 0.774838147 |

| Paired contrast | Effect | Adjusted interval |
| --- | ---: | --- |
| Value minus fixed | 0.133340329 | [0.120444275, 0.147810232] |
| Value minus ordinary | 0.009980653 | [0.005501867, 0.015114329] |

The registered primary gate passes: both pooled lower bounds exceed 0.005
and both mean effects are positive in every fitted seed. Intervals use 4000
paired context bootstraps, equal stratum/fit weights and an eight-comparison
two-sided Bonferroni family of 0.05. The result is conditional on these frozen
fits. The lower bound against the ordinary controller exceeds the effect
threshold by only about 0.000502.

The cross-stratum gate fails. The nominal, high-cost and short-deadline lower
bounds against the ordinary controller are 0.003298, 0.003211 and 0.001589,
respectively; none exceeds 0.005. No advantage in every stratum is established.

The contract pays `b-cost` per hit. The threshold-dependent task reward is an
explicit additional utility assumption, not a consequence of a unit binary
spike payoff. The planner searches the constant-threshold-per-episode family
on a 257-point grid with local refinements. It is not a certified unrestricted
finite-horizon impulse-control optimum.

The value policy used 203,700 analytic context evaluations and about 50.23
seconds of local planning across the 768 contexts. Ordinary batch inference
took about 0.00124 seconds in total, apart from its separately retained
training cost. These implementation measurements use different batching and
do not constitute a matched hardware benchmark. Primary utility includes
per-hit task cost; solver/training time is not converted into that utility.
There is no demonstrated total-compute or energy advantage.

### Native execution and explicit resource feedback

The isolated Rust 1.96.0 bridge executes the original `NeuronRuntime`,
`SparseJournal` and `FileAnchorWitnessStore`, with the original native NDU
candidate evaluator. Nine native tests pass. Seven mechanical scenarios
exercise 15 NDU calls, 15 owner ticks, eight recoveries and seven replay checks.
Completed requests produce no new read attempts. A lost outcome after an
admission commit remains indeterminate and cannot be retried as a fresh read.

The separate credit adapter loads the selected A1 checkpoint and maps upper
voltage drift to the existing cell's lower-distance drift with the opposite
sign. The trained cancellation rate remains zero. The resource dual price pi
changes decision cost and is settled from actual read attempts:

    cost = base_cost + pi * expected_resource
    pi_next = clip(pi + eta * (actual_attempts - target_usage), 0, pi_max)

This adapter has 13 passing mechanical checks, eight actual NDU calls and
seven native owner ticks. After the first read, pi rises from 0 to 0.6. The
next read is still legal, but native NDU selects STOP. A zero-price intervention
on the same observed and physical successor instead selects READ.

| Credit fixture | Actual attempts | Found answer | Physical task return |
| --- | ---: | --- | ---: |
| Feedback enabled | 1 | No | -0.05 |
| Feedback disabled, same model/input/seed | 3 | Yes | 0.85 |
| Failed opened read | 1 | No | -0.05 |

Fewer reads sacrifice task success in this fixture. The result establishes a
real feedback and action path, not improved utility, optimal pricing or energy
savings. Failed opened reads are charged; completed replays do not charge or
update credit twice. The dual is an explicit research adapter, not a claim
that an existing native Organ Credit API has been trained or activated.

The separate credit recovery layer reconstructs all seven original settlements
in three fresh Python processes and matches the uninterrupted account's state,
price, predecessor and record map. Completed replay remains idempotent; three
explicit synthetic accounting continuations also match. Seven missing, corrupt,
reordered or inconsistent-record/witness cases are rejected. Verification uses
seven native inspections and zero task executions, leaving the original input
evidence unchanged. This closes cold-process ledger recovery for readable,
completed records under the serial research contract, not power-loss atomicity.

## Mathematical stability and scope

For distance a>0, diffusion sigma>0 and horizon T>0, the first-passage density is

    f(t) = a / (sigma * sqrt(2*pi*t^3))
           * exp(-(a-mu*t)^2 / (2*sigma^2*t)).

The competing-hit probability is the integral of `exp(-lambda*t)*f(t)`;
survival is `exp(-lambda*T)*S(T)` and cancellation is the remaining mass.
This gives the correct complete expectation and conserves derivative mass.
Its score contains `(a-mu*t)/sigma^2`,
`-1/sigma+(a-mu*t)^2/(sigma^3*t)` and `-t` for mu, sigma and lambda.

On compact sets with a>=a_min>0, sigma>=sigma_min>0, T in a positive finite
interval, and bounded drift/cancellation, each needed density derivative is
bounded by a polynomial in 1/t times `exp(-c/t)` near zero. Dominated
differentiation therefore gives bounded first/second derivatives and a
Lipschitz gradient for the finite fixed-cost objective. The nonnegative-rate
boundary uses one-sided derivatives. This argument avoids the apparent
coalescing-root singularity at mu=lambda=0.

For an L-smooth objective over a convex compact parameter domain and exact
projected gradient steps with alpha<=1/L, the projection inequality and descent
lemma give

    loss(theta_next) <= loss(theta) - alpha/2 * ||G_alpha(theta)||^2,
    G_alpha(theta) = (theta - project(theta-alpha*gradient))/alpha.

Summing bounds the minimum squared gradient mapping after K updates by
`2*(loss_initial-loss_lower_bound)/(alpha*K)`. This is a constrained stationary
point statement, not a global-minimum theorem. Numerical quadrature introduces
controlled empirical error, so the implementation checks actual expected-loss
descent and finite differences rather than claiming the exact theorem applies
without numerical qualifications. Projection keeps sigma above 0.2 in the
registered fits.

The finite meta tree is differentiable away from projection kinks; at kinks
only the appropriate directional/piecewise statements apply. Its derivative
is the sum of `d(path_probability)*leaf_loss` and
`path_probability*d(leaf_loss)`. Enumeration scales exponentially with inner
depth and is used as a verifiable small oracle.

A positive refractory duration and finite hit budget prevent event explosion:
the episode has at most `min(K, floor(T/d)+1)` hits. Bounded price projection
keeps pi finite but does not establish dual convergence for the nonconvex
hybrid task. Local diffusion regularity does not supply whole-domain Holder
regularity across reset/refractory transitions or convergence of sampled deep
Q-learning. Poisson cancellation is not mathematically equivalent to OU leak.

## Reproduction and evidence

Use Python 3.12.14 and the pinned NumPy/SciPy requirements. From repository root:

```bash
python -m pip install -r experiments/first_passage_adaptive/requirements.txt
python -m experiments.first_passage_adaptive.retain_evidence restore \
  --manifest evidence/retained/manifest.json
python -m experiments.first_passage_adaptive.verify_evidence
python -m unittest discover -s experiments/first_passage_adaptive/tests -v
```

The evidence archive contains both pre-confirmation versions, selected models,
all confirmation contexts, every rollout utility, every planner search,
component freezes, one-shot opening registries and original native receipts.
Pieces stay below the repository blob limit. Restoration validates every piece,
archive member and destination. The verifier recomputes retained statistics;
it does not reopen confirmation or select a new model.

See `native/README.md` for the native build and recovery contract. Credit
execution's retained README and source freeze document the selected-model
mapping and feedback intervention. Independent derivative, threshold, native,
confirmation and credit reviews live in `review/`. The additive CI restores
and checks the frozen evidence, runs regressions and rebuilds/replays the
mechanical native fixtures. It does not run a new scientific confirmation.

## Remaining limits

The finite-contract derivative, complete small meta-tree, registered threshold
experiment, real native reads and trained-parameter credit connection are
implemented and evidenced. Three larger claims remain unestablished: superiority
across all registered strata or arbitrary tasks, superiority after full compute
and energy costs, and scalable unbiased training of an arbitrary multilayer
spiking network. The current data cannot close those scientific claims.

Production still requires a canonical complete FPT owner profile, calibrated
readout, authorized product TaskFlow action owner, and target-host concurrency
and durability qualification. The current complete FPT and post-I/O state are
strongly bound research sidecars under a serial trusted runner. No production
activation, concurrent exactly-once or crash-atomic transaction is claimed.
