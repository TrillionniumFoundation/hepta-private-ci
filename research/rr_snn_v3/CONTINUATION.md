# Continuation component: retained stage record

This document preserves the earlier continuation-only stage. The integrated
status, trained network and later evidence are described in [README.md](README.md).

# RR-SNN v3: continuation-valued deadline primitive

Status: **research primitive validated; no new trained SNN or production qualification**.

This is the next bounded implementation after the RR-SNN v2 negative task/cost
results. It corrects the location of renewal costs and provides an independently
checkable reference before another neural architecture is trained. It does not
replace, relabel, or retune the completed v2 test results.

## Model contract

The finite CTMC uses a row generator Q with nonnegative off-diagonal entries.
For a column of post-event values g, the interval continuation is

    C = exp(-rho * dt) * exp(Q * dt) * g.

This propagates values, not a normalized conditional-survival law. Its row sums
are exp(-rho * dt), not one, after discounting. The implementation uses bounded
uniformization with an explicit Poisson-tail bound; floating-point roundoff is
separate from that truncation bound. No Euler baseline is used for validation.

At an announced deadline, each due leg chooses D (drop), R (renew), or E (emit).
For one joint action a:

    J(a) = sum(pre-reset emit rewards)
           - sum(current renewal utility losses)
           + V_after(post-action budget, post-action evidence, renewed mask).

`emit` here is a task action, not evidence of an internal biological spike.
The action first updates the complete joint state. If any output occurs, the
common evidence resets once; all simultaneous outputs read the same pre-reset
evidence. Only then is the continuation evaluated. The sum of all action budget
debits must be affordable. A per-leg independent maximum is not valid under
shared budget or shared reset.

Utility loss and budget debit are separately specified units. A debit changes
feasibility and future state; a utility loss belongs to its renewal branch.
Do not deduct the same loss again if a supplied continuation already includes it.
The continuation callback must be a pure conditional value function of the
post-action state, not a realized future outcome or a hidden oracle label.
Non-due obligations must be retained by the caller's continuation state.

The common-state fixture is deliberately one-cycle: renewed legs pay terminal
value and do not expire again. The separate Brownian example permits decisions
only at t=0, D=1 and H=2; output ends the current cohort. These contracts do not
establish a full asynchronous SNN, repeated-renewal controller, continuous-time
optimal stopping solution, or endogenous financing-price fixed point.

## Direction of the corrected mechanism

With the feasible policy set fixed and a utility fee L on each renewal:

    V(L) = sup_pi [A_pi - L * R_pi],

where R_pi is expected discounted renewal exposure. Thus V is nonincreasing
and convex; optimal renewal exposure is nonincreasing as L rises.

Output counts need not increase. Dropping or not starting a cohort can be
optimal. An output-region expansion follows only when the increased fee belongs
to a current obligation that output cancels, and post-output value is independent
of that fee. A reset that starts new fee-bearing obligations breaks that premise.

The original v2 mapping put some deadline pressure into output cost. In its
restricted, unclipped scalar model dh/dc > 0. Correct evaluation of that formula
does not make renewal loss and output cost economically interchangeable.

### Finite CTMC regression with a hand calculation

Before the deadline the generator is

    Q = [[0, 0], [log(2), -log(2)]],

starting in the second state. After one time unit the two evidence outcomes
0.6 and 1 have equal probability. Immediate output at time zero is 1; renewal
leads to terminal reward 1.5. Initial budget is 2; renewal and output each cost
one budget unit. Drop is free.

| Placement | Renewal fee | Immediate output | Wait value | First action |
| --- | ---: | ---: | ---: | --- |
| Renewal continuation | 0 | 1 | 1.5 | Wait |
| Renewal continuation | 0.8 | 1 | 0.85 | Emit |
| Incorrectly shifted to each output | 0.8 | 0.2 | 0.7 | Wait |

The last row is a deliberately different objective used as a regression
counterexample; it is not a fair competing neural architecture.

### Brownian cross-check

Y0=1, sigma=0.2; drift before D=1 is -0.2, and after renewal until H=2 is +0.7.
Output ends the cohort; budgets are as above. At D the correct continuation is

    G_L(y) = max(0, y, E[(y + 0.7 + 0.2 Z)^+] - L).

The positive Gaussian moment is m Phi(m/s) + s phi(m/s).
Normal integrals are evaluated with adaptive Simpson quadrature over [-10,10].
The omitted normal tails are negligible relative to the stated test tolerance
for these fixed linear-growth payoffs; this is not a generic quadrature error
guarantee for arbitrary user callbacks.

The independently simplified wait values are:

- L=0: positiveNormalMean(1.5, sqrt(0.08)) = 1.500000002847777.
- Correct L=0.8: positiveNormalMean(0.8, 0.2) = 0.8000014290516865.
- Shifted output cost=0.8: positiveNormalMean(0.7, sqrt(0.08)) =
  0.7006125845197289.

Nested numerical integration agrees within 1e-13 in this fixture. This example
validates cost placement; it is not a benchmark of learned-policy quality.

## Shared-budget and reset counterexample

Two legs mature simultaneously at evidence x=1 and reset x=0.
Current emission rewards are (3x, x); renewed terminal values are (1.5x, 3x).
Each renewal loses 0.5 utility and consumes 1 budget; each emit consumes 2.

With budget 3, the legal joint action values are:

    DD=0, DR=2.5, DE=1, RD=1, RR=3.5, RE=0.5, ED=3, ER=2.5.

EE is unaffordable. RR is optimal. Incorrectly retaining pre-reset evidence for
the renewed leg would assign ER=5.5 and select the wrong action.

With budget 1 only DD/DR/RD are affordable and DR=2.5 is optimal. Independent
per-leg renewal would incorrectly demand budget 2. With budget 4, EE=4 verifies
that both simultaneous outputs use the pre-reset evidence.

For budget 3 and common renewal loss L the exact optimal value is

    max(4.5 - 2L, 3).

The 41-point loss sweep checks this envelope, monotonic value, convexity and
nonincreasing optimal renewal exposure, including the tie at L=0.75.

## Anticipation without realized-future leakage

A separate two-deadline reference retains the non-due second obligation.
At t1, evidence=1 and budget=2. The current first leg has emission reward 2.5,
terminal retention reward 1 and fixed renewal loss 0.25. At t2 the second leg
has emission reward 1, terminal retention reward 3 and renewal loss L2.
Renew and emit each debit one budget unit. A global output resets evidence to
zero, affecting the continuation of retained obligations. Q=0 and rho=0.

Only the future second-leg loss changes:

| Future L2 | Current R value | Current E value | Current D value | Current best |
| --- | ---: | ---: | ---: | --- |
| 0.5 | 3.25 | 2.5 | 2.5 | Renew |
| 2 | 1.75 | 2.5 | 1 | Emit |

All current costs, budget and evidence are identical. If L2 is only observed at
t2, the current actor receives the public high-fee probability p and integrates
over it. The values are R=3.25-1.5p, E=2.5 and D=2.5-1.5p.
It renews for p=0.25 and emits for p=0.75. The realized future draw is not an
input to the current decision. This is a model-based mechanism check, not a
learned-policy generalization result.

A stronger information-timing fixture uses L2=0.5 with probability 0.75 and
L2=4 with probability 0.25. Correct current-max / future-expectation /
observed-future-max ordering gives R=2.625. Forcing the future action to be
chosen before observing its fee yields only 2.5; letting the current action
see the future fee produces an impermissible 3.0625. Independent forward
policy enumeration checks all three quantities.

## Validation and reproduction

Run from the repository root with Node.js:

    node research/rr_snn_v3/validate.cjs

No packages, filesystem writes, network access or model downloads are required.
The same module and validation function were actually evaluated in the
conversation's V8 JavaScript executor. The Node CLI command itself has not been
run in this session: the filesystem exec service failed its initialization
handshake. Node/V8 source syntax is ordinary dependency-free CommonJS.

The evidence covers:

- 64 two-state generators against an independent closed-form transition;
- 64 semigroup compositions, probability mass and discounted-value mass;
- an independently computed discounted vector and loss-timestamp check;
- joint budget, simultaneous output, reset and shock-order golden cases;
- the exact loss envelope and cost-placement counterexamples;
- Brownian quadrature against simplified Gaussian expectations;
- independent enumeration of 27 two-stage contingent policies for each public prior;
- item-permutation invariance and local loss sensitivities away from policy ties;
- rate/time scale invariance across seven reciprocal scales;
- rejection of 17 invalid generator, resource, loss, probability and work-budget inputs.

Independent review of the initial implementation found that an absolute floor
in row-mass tolerance accepted an invalid tiny-rate generator; with a long
interval it produced row mass 1.6321. Validation now uses the actual exit-rate
scale and includes both that rejection and seven valid reciprocal rate/time
scales. The original commit remains in history. See independent_review.json.

See validation_results.json for actual numerical errors and all raw fixtures.
These deterministic checks are development/verification fixtures, not holdout
performance statistics. No bootstrap interval, training gain, generalization,
RSS, throughput or p99 claim is inferred from them.

## Next SNN integration gates

The candidate is not yet a network. Before a new performance experiment:

1. Connect an actual spike-emitting operator to this value recursion. Specify
   which obligations an output cancels and what a reset creates.
2. Advance old controls to an event, apply ordered resource events, observe,
   then perform the joint action. Preserve terminal T-minus salvage semantics.
3. If Q depends on resource or memory state, select the post-action Q and reset
   start state; do not reuse stale pre-action controls.
4. Account for obligations and resource events during refractory time.
5. Train against a declared objective; direct terminal-utility optimization and
   teacher-action likelihood are distinct objectives.
6. Freeze architecture, baselines, data sources, budget and independent future
   windows before opening new holdout. Keep the v2 test set as historical
   evidence, not an endlessly reusable selection set.
7. Repeat actual event, gradient, calibration, recovery and end-to-end cost
   checks. A planner's table lookups are not evidence of a learned SNN advantage.

## Hepta interface status

The inspected main is f8c9419df6ddeb36ff8b522a50219981fb8d9345.

Existing code already contains NeuronRuntime recovery, journal segment rollover,
SparseJournal.commit and FileAnchorWitnessStore.compare_and_swap. Generic
journal/CAS/witness infrastructure should be reused rather than declared absent.
The registered runtime is bound to SparseConfig/SparseCheckpoint and its five
Q24 vectors; this research module does not change that production profile.

The remaining RR-specific work is a separately versioned complete stochastic
joint-state profile, actual owner integration and recovery evidence. Preserve
the existing V1 unknown-field rejection. Do not insert RNG, trace, deadline and
budget fields into the old V1 envelope and claim it is the registered state.

The five external/upstream gates remain open:

- verified target-host/dot execution capability;
- actual inference-owner invocation receipt and witness;
- immutable independent real future event/outcome windows;
- measured 64/256/1024/4096 real Cell workloads;
- registered RR joint-state owner/profile with real journal/CAS/recovery.

This branch adds no authority grants, no model installation, no production
activation and no fabricated owner or future-window receipt.

## Sources

- He and Xiong, Rollover Risk and Credit Risk (2012):
  https://www.princeton.edu/~wxiong/papers/rollover.pdf
- Existing owner interface:
  codex-rs/hepta-infer-worker-host/src/model_worker.rs
- Existing runtime and witness:
  codex-rs/hepta-neuron/src/runtime.rs
  codex-rs/hepta-neuron/src/witness.rs
- Existing state and protocol:
  codex-rs/hepta-neuron/src/sparse.rs
  codex-rs/hepta-neuron/src/protocol.rs
- Future-window admission:
  codex-rs/hepta-intelligence-eval/PRODUCTION_CONTRACT.md
  codex-rs/hepta-intelligence-eval/EVIDENCE_ADMISSION.md
