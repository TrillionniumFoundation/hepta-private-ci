# Research-only two-cell coupled regenerative QVI — bounded P0 evidence

Status: **DRAFT / DENY_ALL / NOT_PRODUCTION**. Additive continuation of research PR #4387. All formulas refer to a *neural analogy*, not original He–Xiong corporate-debt pricing or their equity/default equilibrium. Code does not touch Rust, control authority, checkpoints, GPU, model training, pretrained multimodal encoders, or production release.

## Precisely scoped model

Two independent arithmetic Brownian states `Xi`, with independent drift/diffusion and a **shared positive discount** `rho`. Between events, the generator is the sum of the two one-dimensional generators. One and only one action is chosen at a time:

- `WAIT`: continuous stochastic evolution and discount.
- `FIRE 1`: immediate `x1-cost1`, freeze **both** coordinates during refractory time `tau1>0`, reset only first coordinate to `reset1`, then resume with discounted value `exp(-rho*tau1)*V(reset1,x2)`.
- `FIRE 2`: analogously `x2-cost2+exp(-rho*tau2)*V(x1,reset2)`.

Discrete state-space **finite** QVI:

```
max( (L1_h+L2_h-rho) V,
     x1-cost1+exp(-rho*tau1)*V(reset1,x2)-V,
     x2-cost2+exp(-rho*tau2)*V(x1,reset2)-V ) = 0.
```

At all four outer edges, outward Markov jump rates are suppressed (a blocked-jump / zero-outflow finite CTMC). This is an artificial finite-state boundary model. **No continuum reflected-Brownian Neumann error theorem is asserted.**  Interior rates are centered if nonnegative and upwind otherwise. Off-grid resets use positive/convex piecewise-linear interpolation. Discount `rho>0`, strictly positive refractory time, and finite generator rates imply every branch of the discrete Bellman operator has sup-norm contraction factor <1. A large but finite positive impulse cost is allowed, including an inert cell with no profitable `FIRE` in the rectangle.

## Independent checks and baseline

1. Sparse Howard-style policy iteration (linear solves) versus **Jacobi Bellman** value iteration (no policy or matrix solve): all 13², 21², 33² grid comparisons pass (`max |Vpolicy-Vjacobi|<2e-8`, selected settings). Both use the **same discrete state model** and are NOT two independent PDE spatial discretizations.
2. Separately coded scalar-loop QVI residual and action complementarity; the latter does not call solver residual routines.
3. Invariance when cells are swapped; identical-cell value symmetry; observed action competition with all three actions present.
4. If both interventions are strongly unprofitable, the value is exactly zero. If cell 2 is inert, the 2D solution is invariant along x2 and agrees with a separately programmed 1D reflected CTMC Jacobi solver.
5. Selected grid refinement at `(x1,x2)=(0.5,0.5)` for 17²/33²/65²; **not** a global convergence guarantee. At `(0.47,0.31)` the successive differences are **not** monotone and are not hidden.
6. Upwind/drift dominance, off-grid reset, convex interpolation, malformed domains/precision alias for tiny refractory, solver-budget exhaustion all fail closed.
7. Fixed-policy Monte Carlo uses exponential CTMC waiting times, Bernoulli-interpolated reset and explicit refractory, and independently checks two states with seeded 2500-episode statistics each. **This is a statistical consistency check**, not a deterministic proof.
8. Seeded 90 finite-admissible configurations on 13×15 grids, including six independent Jacobi cross-checks. This is nowhere near coverage of the full parameter domain.

## Reproduce

Under an upstream checkout with `experiments/hcsn_hx_unified_v3/stopping.py` (unchanged, expected Git blob `d165ed777990bbf8f3606b58e1b0991de59a1544`), run:

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_coupled_qvi
```

Dependencies: Python 3.13, NumPy, SciPy (SciPy only used in independent sparse solver); no GPU or Rust. A standalone local archive can include upstream stopping.py for execution, but the PR must **only** add `coupled_qvi.py`, `test_coupled_qvi.py`, and this gate.

## Remaining blockers (ALL OPEN)

- True all-domain **HX financial fixed-point equilibrium** and positive-equity/obstacle proof; existing parent negative witnesses retained.
- Certified continuum/free-boundary derivative and interval numerical-error bounds, and asymptotic/low-precision singular limits.
- Non-frozen asynchronous refractory and time-continuous multi-cell event consistency; scaling this 2D finite CTMC to 64+ real cells remains unproved. Finite grid dimensionality scales exponentially and this code is **not** a scalable training/runtime kernel.
- P1 matched Call/Risk/Margin mechanism advantage: prior negative ablations remain unoverridden.
- P2 robust Selective Copy/MQAR/overwrites/irregular-time long-memory; P3 actual four-modality encoders; P4 native Rust/GPU and 64/256/1024/4096-cell throughput/RSS/p95/p99/energy/recovery; P5 equal-budget backbone superiority.

A passing local suite MUST NOT grant HX or production admission; leave draft and DENY_ALL.
