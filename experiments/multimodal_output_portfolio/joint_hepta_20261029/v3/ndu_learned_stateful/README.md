# Learned stateful paid interventions: finite reference experiment

**Disposition: semantic gap closed under a stronger paid calibration assumption;
no new RL advantage and no positive primary lifecycle gate.** This extension
estimates an unknown joint kernel and lets interventions change an observed state.
It preserves the earlier [18-cell known-law experiment](../ndu_identification/README.md).
The method is classical plug-in belief DP; it is also the strongest same-data
planning baseline. [Nearest work](PRIOR_ART.md) and [finite bounds](THEORY.md)
state the established ingredients and the limits of any novelty claim.

## Contract and access assumptions

A hidden binary `H` is fixed during deployment. The observed state `z` is 0 or 1.
The initial prior is 1/2, initial state 0. A fixed external scorer awards
`1{terminal decision=H}*(.55+.45*z)`. Each of two actions, inspect and repair,
has an unknown 12-outcome row `(label,duration,next_z)` at each `(H,z,action)`.
Labels are failure/0/1; durations are 1/3 **simulated clock units**. The next state
changes both subsequent observation laws and the attainable terminal quality.
The four locally prespecified worlds cross restoring/damaging repair with weak/strong
inspection information. The estimator is an unrestricted multinomial table and
does not use this generator factorization or know which world it is in.

At most two launches are allowed. Every integer cap from 1 to remaining time is
legal. A completion, including a failure, applies its next state. Duration>cap
returns only `(timeout,cap,current_state)`; cancellation preserves the state.
This assumes transitions occur atomically at completion and no work remains in
flight. It does not describe a system whose state changes before cancellation.
Every launch pays once, including failure and cancellation. Utility is fixed as
terminal quality minus launch fees minus `.02*actual consumed simulated time`.

**Calibration access is additional supervision.** A resettable simulator/lab can
instantiate a requested `H`, prepare a specified `z`, and return an uncensored
joint sample. Each sample pays `.005` launch, `.003` label, `.002` state reset,
and `.001` per full simulated time unit. All failures are included. Deploying the
controller receives neither `H` nor access to this labeled reset interface.
This does not solve learning from arbitrary unlabeled trajectories or unobserved
state changes. Every price is a synthetic score-unit price, not a provider price.
No real provider was paid; no LLM was run.

`model.Policy` receives a purchased estimated table and observable history state.
The true generator is confined to `study.py` and evaluation. `known_oracle` gets
extra true-law knowledge explicitly as a diagnostic and is excluded from claims
of deployable, acquisition-cost-adjusted improvement.

## Freeze, experiment, and controls

[protocol.json](protocol.json) and [freeze.json](freeze.json) were locked at
2026-11-06 02:57:19 UTC, before any calibration or confirmation bank was generated.
This records a local source/protocol freeze before the run; it was not an
independently timestamped external preregistration.
The grid contains 4 worlds x 2 calibration seeds x 3 prespecified row sample
counts (16/256/8192) x 3 deadlines (0/1/4) x 2 fees (.025/.3): **144 cells**.
The smaller data sizes are nested prefixes, not adaptive sampling decisions.
There are 24 fitted banks, each with eight labeled rows. Four separately seeded
confirmation banks contain 4,096 independent tasks each. The same task's hidden
hypothesis and action/state/step random slots pair all frozen policies. Reusing
random numbers is a simulator design; every executed policy launch is charged.

Policies are prior STOP, same-data one-step VOI with replanning, same-data exact
plug-in DP, a duration-posterior ablation, a state-transition-planning ablation,
and the known-law diagnostic. The duration ablation still respects actual time
and observed next state. The state ablation predicts future value as if state
persisted, but uses the newly observed state at the next actual decision.
These deliberately misspecified ablations are not the strongest baselines.

The 5% family budget is split equally between simultaneous kernel bounds and
confirmation bounds. The kernel bound unions over 8 rows x 24 fitted banks;
smoothing adds a declared deterministic error term. The confirmation bound unions
over 144 absolute utilities and 576 paired contrasts, with bounded score range.
No Monte Carlo coverage claim or seed/sample-size selection is made. Observing
all bound events in this finite bank is not an empirical proof of 97.5% coverage.

## Results, including failures

| Samples per row | Observed maximum row-TV range | Simultaneous TV radius | Maximum true oracle regret |
| ---: | ---: | ---: | ---: |
| 16 | .24425–.40726 | 1.00000 | .11430125 |
| 256 | .08258–.13823 | .20653 | .01232977 |
| 8192 | .01639–.02116 | .03319 | .00064350 |

| DP versus comparator, true enumerated utility | Wins | Ties | Losses |
| --- | ---: | ---: | ---: |
| Prior STOP | 46 | 96 | 2 |
| Same-data myopic VOI | 0 | 143 | 1 |
| Duration-posterior ablation | 22 | 120 | 2 |
| State-planning ablation | 19 | 118 | 7 |

The two below-STOP cells are damaging/weak, seed 117, n=16, deadline=1
(gap −.05340125), and seed 431, n=16, deadline=4 (−.01773864), both fee=.025.
The loss to myopic is damaging/weak, seed 431, n=256, deadline=4, fee=.025
(−.00431442). None was removed. A separate hand-built unit test demonstrates
that the solver can choose a useful two-step state intervention that myopic
rejects; that test is not a win in the registered confirmation experiment.

All 24 observed TV events and all 144 regret / 576 comparative model inequalities
hold in exact trajectory evaluation. Only 8 model certificates against STOP
and 2 against the state ablation are positive before acquisition amortization;
none against myopic is positive. The paired confirmation lower bounds are
positive in 32 STOP, 0 myopic, 2 duration and 12 state comparisons. Validity and
useful positivity are separate endpoints.

## Full acquisition costs and break-even

The actually collected 524,288 calibration samples cost **6,290.148 score units**.
The full confirmation audit executes 3,538,944 policy episodes with 1,229,038
launches, 83,994 failures and 378,604 cancellations; its charged total is
**82,576.630**, including labels/resets even for STOP episodes. Global research
acquisition is **88,866.778**. Hardware runtime was separately measured as
13.194 seconds through final result assembly (excluding the final JSON/manifest
writes); it is not added as simulated time or priced as provider compute.
Hardware/engineering costs are unpriced, so lifecycle figures are optimistic if
those resources have a nonzero additional monetary cost.

The primary lifecycle endpoint is fixed at 1,000 deployments. Each candidate
carries its entire maximum-size world/seed calibration bank, including unused
prefix samples, plus its own confirmation receipts. Prefix-only acquisition
costs are labeled counterfactual. Other same-data policies carry the same full
training bank; their common calibration expense cancels in paired comparisons.
STOP needs no acquisition. This per-controller allocation is separate from the
larger global research bill above; charging that whole bill is still less
favorable. **All 144 primary absolute lifecycle lower bounds are negative and
0/144 cells pass the positive-net gate.**

For example, restoring/strong, seed117, n8192, deadline4, fee.025 obtains true
utility .60418885 versus STOP .275 before acquisition. Its allocated setup cost
is 1,296.306. The diagnostic expected break-even against STOP is about 3,938
deployments, conditional on the same stationary distribution continuing. This is
not an actual saving or a confidence guarantee. The registered secondary volume
10,000 makes absolute utility lower bounds positive, but does not produce an
advantage over myopic or establish a new algorithm. No volume was increased to
repair the primary failed gate.

## Reproduction and evidence

From the repository root:

```bash
python -m unittest experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_learned_stateful.test_model -v
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_learned_stateful.study --output evidence/reproduction
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_learned_stateful.audit
```

Ten mechanism tests pass. [The audit](evidence/validation.json) independently
sums unnormalized hidden-state masses and solves the finite DP from raw joint
rows: maximum value discrepancy 1.11e−16, ledger discrepancy 1.53e−16. This is
internal numerical review, not external peer review. Enumerations use floating
point. Replacing scalar posterior arithmetic by a NumPy dot changes some fitted
terminal ties, with a maximum true-value shift .00047817; the audit retains that
sensitivity and verifies the actual frozen policy without changing its source.

[Results](evidence/registered_v1/results.json), [manifest](evidence/registered_v1/manifest.json),
[source snapshot](evidence/registered_v1/source_snapshot.json), and raw compressed
[calibration](evidence/registered_v1/calibration_raw.npz),
[confirmation](evidence/registered_v1/confirmation_raw.npz), and
[paired utilities](evidence/registered_v1/paired_utilities.npz) are retained.
Calibration arrays use `(H,z,action,sample)` and lexicographic `(label,duration,z')`
indices; confirmation contains evaluator-only `H` and uniform slots. Utility axes
are result-case order, protocol-policy order, and paired task index.
Results SHA-256: `5e3c479a257da5776219227690cdaeef03ee7fb33ee3b0a8c8f69040f1f9d221`.
A fresh output directory is required; source/protocol mismatch aborts. Reruns
reproduce arrays and scientific values; measured runtime is naturally variable.
