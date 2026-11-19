# Preregistered local synthetic routing diagnostic

Protocol version 1, fixed before first experiment run, 2026-10-23.

## Question and difference from NDU
Can a nonrecursive, frozen, finite-context router enforce a resource cap and explicitly fall back when chosen-action logs do not identify an alternative's reward? This is a diagnostic control, not a reproduction of CLUCB, SPIBB, or the Agrawal algorithm and not a superiority claim against NDU. There is no Bellman backup, learned critic, topology mutation, decoder, natural cohort, or recursive credit replay.

## Fixed design
- Seeds: integers 0 through 31, all reported; no seed selection or tuning after viewing outcomes.
- Four contexts, two actions; action 0 is the baseline. Costs are declared synthetic integer units 1 and 3, not measured model FLOPs, latency, energy, or money.
- Training: 4096 IID uniform-context samples per seed. Only chosen action, Bernoulli reward, cost, and logging propensity are supplied to the learner. Full-support logging samples each action with probability 0.5. Deficient logging takes baseline only in contexts 2 and 3, and randomizes equally otherwise.
- Evaluation: 4096 fresh IID uniform-context samples, independent RNG stream from training. Frozen policies share prospective potential-outcome uniforms for paired diagnostics. Evaluation outcomes and generator means are never supplied to fitting or routing. The auditor knows the synthetic reward law.
- Resource cap: floor(1.75 * evaluation count); reserve one baseline cost for each remaining request. All policies have the same cap. Baseline cannot overspend; expensive action is admitted only if all remaining baselines remain feasible. This is a feasibility filter, NOT an optimal knapsack allocator.
- Policies: always-baseline; empirical per-context mean with pooled same-action mean extrapolation when a cell has no samples; conservative empirical router with both cell counts >= 32 and alternative lower confidence bound above baseline upper confidence bound. Ties select baseline. Radius = sqrt(log(2*K/delta)/(2*n)), K=8 cells, delta=0.05; confidence coverage pertains only to IID bounded stationary training-cell means and is not a distribution-shift guarantee. No lifetime or prefix realized-reward safety claim.
- Full-support reward means (baseline, alternative): [(0.6,0.9), (0.6,0.8), (0.6,0.55), (0.6,0.95)].
- Deficient-support twins: identical training logs, with supported alternative means 0.9/0.8, baseline 0.6 everywhere; unlogged alternatives in contexts 2/3 have evaluation means either 0.95 (high world) or 0.0 (low world). These two laws induce the same observed training distribution. Their learner inputs and resulting policy must be byte-identical. Pooling is deliberately exposed as an assumption, not identified evidence.
- Reward-law-shift negative control: use full-support training, but evaluation alternative means are 0.05 in contexts 0,1,3 and 0.55 in context 2; baseline remains 0.6. No adaptation or post-hoc threshold change is allowed.

## Falsifiable outcomes and reports
Report every seed, training hashes/counts, policy maps, realized reward, evaluator-known conditional expected reward, spend, cap interventions, unsupported action choices, and baseline-paired gains. Check exact hard-cap feasibility, exact twin log/policy equality, and zero unsupported conservative choices. Report seed-mean differences with a descriptive 95% t interval (31 degrees of freedom, critical 2.039513), explicitly unadjusted across comparisons. Check whether the full-support mean gain interval is positive and the reward-shift mean gain interval is negative; preserve failures rather than changing protocol. Twin-world value reversal is a diagnostic possibility, not a required software assertion. No optional stopping.

## Evidence limits
All rewards and resource costs are generated synthetic data. Independent RNG streams are not independently controlled real observers. An actual CPU process runtime is recorded only as harness runtime. None of the six scientific blockers is closed. This is not OPE: static-policy IPS/DR cannot simply evaluate the history-dependent budget filter. No propensity-based safety claim is made. A real trial still requires callable conditional generator adapters, independently collected natural cohorts and rewards, actual full-path metering, preregistered future/retention windows, and observer trust roots.

## Primary sources consulted
- Agrawal, Devanur, Li, COLT 2016, contextual bandits with global resource budgets: https://proceedings.mlr.press/v49/agrawal16.html
- Laroche, Trichelair, Tachet des Combes, ICML 2019, baseline bootstrapping under uncertainty: https://proceedings.mlr.press/v97/laroche19a.html
- Sachdeva, Su, Joachims, KDD 2020, deficient logging support and extrapolation assumptions: https://arxiv.org/abs/2006.09438
- Dudik, Langford, Li, ICML 2011, doubly robust evaluation: https://icml.cc/2011/papers/554_icmlpaper.pdf
- Vowpal Wabbit official contextual-bandit input contract and implementation examples: https://vowpalwabbit.org/docs/vowpal_wabbit/python/latest/tutorials/python_Contextual_bandits_and_Vowpal_Wabbit.html

These motivate a deliberately simpler finite-context diagnostic. Their algorithmic guarantees are not transferred to this implementation.
