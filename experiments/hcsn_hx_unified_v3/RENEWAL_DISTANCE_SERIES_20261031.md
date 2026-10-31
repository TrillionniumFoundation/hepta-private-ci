# P0/P2: finite-horizon Brownian regenerative event series

Status: **RESEARCH ONLY / DENY_ALL**, not a production activation or complete He–Xiong mathematical kernel. Base: stacked PR #4489, HEAD `1bf388463a48ba6286afe0811618b5b8bd900636`; upstream `stopping.py` exact Git blob `d165ed777990bbf8f3606b58e1b0991de59a1544` (reproduced locally with matching byte hash).

## Derivation

For a scalar time-homogeneous Brownian state `dX=μdt+σdW`, a **fixed upper** FIRE threshold `b`, reset `r<b`, deterministic refractory `h>=0`, discount `ρ>0`, and fixed nonnegative boundary payoff `b-K`, let `T_d` be the first hitting time of a level at distance `d>0`. Define:

- `Gρ(d,T) = E[exp(-ρ T_d) 1{T_d<=T}]`, with `Gρ(d,T)=0` if `T<=0` and `d>0`.
- `ν=sqrt(μ²+2ρσ²)`, `κ=(ν-μ)/σ²`, `A=exp(-ρh-κ(b-r))<1`.
- The independent two-normal-tail formula for `Gρ` is
  `exp((μ+ν)d/σ²) Φ(-(d+νT)/(σsqrt(T))) + exp((μ-ν)d/σ²) Φ(-(d-νT)/(σsqrt(T)))`.

The **strong Markov property**, spatial translation invariance and independent increments make successive reset-to-threshold hitting times equal in law to first hitting a more distant level. Consequently, starting below the boundary `x<b`:

`E[sum_{spikes t_j<=T} exp(-ρ t_j)] = sum_{n>=0} exp(-ρ n h) Gρ((b-x)+n(b-r), T-nh)`.

Starting at or above `b`, there is one immediate spike and the sum for `n>=1` uses distance `n(b-r)`. If only `n=0,..,N-1` have been evaluated below threshold, the **exact-model truncation remainder** is bounded by `exp(-κ(b-x))*A^N/(1-A)`; for initially active state the omitted future terms from index `N` onward are bounded by `A^N/(1-A)`. A tighter optional envelope follows from Markov/Chernoff: for any `a>=0`, `Gρ(d,t)<=exp(a*t-κ(ρ+a)d)`; after missing event index `N`, the series remainder is bounded by `exp(a*(T-N*h)-ρ*N*h-κ(ρ+a)*d_N) / (1-exp(-(ρ+a)*h-κ(ρ+a)*(b-r)))`. Minimize over a finite predetermined nonnegative tilt grid, including `a=0`, and refuse if none meets the tolerance. This avoids an otherwise enormous `ρ≈0` geometric bound for short finite horizons without pretending to certify floating-point roundoff. With positive refractory, no spike can occur for `n*h>T`; with `h=0`, adaptive truncation uses the same geometric upper bound. The implementation refuses an insufficient maximum-term budget.

Taking `T -> infinity`, the series equals `exp(-κ(b-x))/(1-A)` below threshold. Multiplication by `(b-K)` gives the *same scalar threshold-policy value* as `stopping.regenerative_value`. Above threshold the initial payoff is `(x-K)`, **not** `(b-K)`; only future events pay `(b-K)`. This is a policy evaluation identity, not proof that an arbitrary threshold is globally optimal. Tests independently obtain the stationary threshold using Brent smooth fit.

## Reproducibility

From repository root (with Python, SciPy, NumPy):

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_renewal_distance_series
```

Twelve locally executed tests passed (0 skipped). The pre-submission local test environment used Python 3.13.5, SciPy 1.17.0, NumPy 2.3.5. Numerical evidence:

- 108 fixed-parameter first-hit cases across positive/zero/negative drift, three distances, three discount rates including zero, and three time horizons were compared against **independent integration of the positive first-hit density**; worst absolute discrepancy was `3.3306690738754696e-16`.
- Four drift signs/regimes × three initial states were tested against the infinite-horizon stationary QVI value at horizon 120, including immediate FIRE above threshold.
- 20,000 independent positive-drift Wald trajectories: finite-horizon analytic discounted event count `0.96942873348`, sample `0.96738451078 ± 0.00450183531` standard error.
- 30,000 defective negative-drift trajectories, with an independently sampled Bernoulli probability of eventual hit: analytic `0.15459930123`, sample `0.15372530653 ± 0.00189782016` standard error.
- Zero refractory, negative drift non-hit mass, horizon zero, truncation residual, physical-domain refusal and numerical-resolution refusal were covered. A tiny-discount, large-drift Chernoff-tail fixture terminates in fewer than 40 terms while the original infinite-horizon geometric envelope would remain unusably loose.

These are **local** unit tests, not a full repository run, GitHub CI, directed-rounding interval arithmetic, a formal proof, GPU FP32/BF16 tests or real encoded multimodal training. The `omitted_events_upper_bound` excludes binary-floating-point and normal-CDF approximation error. Any distribution shift away from homogeneous Brownian drift/diffusion, fixed threshold, deterministic refractory, and exact reset invalidates the closed series as stated.

## P0–P5 gate impact

- **P0 OPEN:** strong exact-model cross-check for the simplified regenerative QVI; it does not certify the original coupled He–Xiong bond/equity equations, endogenous boundary, full parameter domain, gradients or device precision.
- **P1 OPEN:** no new matched Call/Risk/Margin causal-benefit evidence; ordinary matched gates remain valid controls and historic negative results remain.
- **P2 OPEN:** exact scalar repeated-event finite-horizon reference added; task-level selective memory, MQAR, long unseen lengths, heterogeneous event streams and arbitrary crash recovery unverified.
- **P3 OPEN:** no real four-modal encoder quality evidence in this increment.
- **P4 OPEN:** no new Rust/GPU/64–4096 physical-cell energy or recovery evidence in this increment; earlier R8 native-owner research is distinct.
- **P5 OPEN:** no fair net advantage over tuned Transformer/SSM or authorization to scale.

No activation, merge, production hook, release tag or false PASS signal is introduced. Preserve `production_activation=false` and `all_scientific_blockers_closed=false`.
