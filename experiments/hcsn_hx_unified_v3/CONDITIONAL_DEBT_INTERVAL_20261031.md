# HCSN P0 conditional debt-error certificate (2026-10-31)

Status: RESEARCH_ONLY / DENY_ALL / NO_GO. Stacked on PR #4499 exact HEAD 1d44dcd5fb0f7d2bf766298a58a8db71369ebe65. Existing financial HX formulas, historical negative evidence, native execution and production authorization remain unchanged.

## Why this matters

PR #4499 discovered that the independent debt PDE and first-hit debt quadrature disagree on coarse financial STOP decisions, even where the finite-grid Bellman residual is small. An exact-rational certificate on a fixed approximate debt array alone does not settle cashflow uncertainty.

The new source hx_conditional_debt_interval_gate.py is a **conditional finite-dimensional perturbation certificate**, on the same input fields as hx_joint_pde_obstacle.py. Required caller-supplied decimal strings debt_error and upper_equity_error must cover absolute errors in all interior debt cashflows and the upper equity boundary. Their correctness is NOT proved by this module; they are external hypotheses.

For d=r+qL+qR, gamma=(qL+qR)/d < 1, nominal fixed-grid residual R, debt error e and upper equity error u:

    E = max(u, (R+(e+qR*u)/d)/(1-gamma))
    D = ((qL+qR)*E+e)/d

The true value deviation is bounded conditionally by E and the continuation value deviation by D. A grid node is conditionally CONTINUE only if nominal continuation c > D, STOP only if c < -D; otherwise it is AMBIGUOUS. Exact Fractions apply to the stored *quantized binary64 operator*, not the true continuum data. A conservative lower zero-equity boundary is required, and invalid/untrusted decimal errors, nonfinite state, resource overruns, wrong financial domain and noncontraction refuse.

## Actual local validation

Command from repository root:

    python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_conditional_debt_interval_gate

Python 3.11 standard-library test harness: **9/9 methods PASS** (0 skipped). Synthetic lattice checks include exact STOP with zero perturbation, 31 ambiguous nodes when uncertainty grows, far-field uncertainty propagation, continued-action sign on numerically converged positive-cashflow grid, residual amplification, invalid decimal/domain refusal and mandatory production=false flags.

Exact tested-and-read-back Git blob SHA1:
- Source: aff677714e8307e16b4c0b6e29512b7bab70b649
- Test: cd35fe321985a37393b3c403894f6e4d8d58b452

This increment has **not** run the full upstream checkout or actual PR #4499 401-node numerical data; no whole-repository CI claim. Synthetic unit tests are not physical financial certification.

## Still blocking

Before applying the perturbation bound to the real HX process, independent rigorous debt/upper boundary error enclosures must verify e and u, including maturity-time corner, extreme assets, and default discontinuity. Cross-solver differences do not automatically upper bound either error. P0 full endogenous global equilibrium, continuum and financial precision remain OPEN; P1/P2/P3/P4 OPEN and P5 BLOCKED. No scientific or production admission is upgraded.
