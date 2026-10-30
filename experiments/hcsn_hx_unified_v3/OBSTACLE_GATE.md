# P0 obstruction: local curvature rejection and a frozen-cashflow obstacle oracle

**Research only — DENY_ALL.** Stacked on HCSN #4377 at inspected source
`166ee63c563d2df065c279ba312d0bcbc539cbce`. The two new Python files
`obstacle.py` and `test_obstacle.py` do not alter the existing financial
closed forms, scalar stopping kernel, research reports, Rust/GPU runtime,
Cell owner, production permissions, or training evidence.

## 1. Necessary mathematical rejection, not all-domain certification

For an algebraic HX smooth-fit candidate with default asset boundary `b`,
let `x=log(V/b)`. With financial continuation cashflow

    f(V;b)=payout*V-(1-tax_shield)*coupon
          +bond_value(V,maturity;b)-principal/maturity,

the financial ODE and smooth fit at `x=0` give

    E(0)=E_x(0)=0,
    E_xx(0+)=-2*f(b;b)/volatility**2.

The finite-maturity bond recovers `recovery*b/maturity` at `b`, so
`f(b;b)` is evaluable without subtracting neighboring equity values.
If `f(b;b)>0` by a conservative floating-point sign tolerance, then
the candidate has negative continuation equity immediately above `b`;
it is **rejected**. If `f(b;b)` is close to zero, the sign is unresolved.
If it is negative, the local test passes, but **global admissibility
remains unproven**. Finite sampled continuation-equity negatives independently
cause a rejection. Every `CandidateAudit.certified` field is `false`.

This test is a necessary boundary inequality. It is *not* a proof that a
globally admissible boundary exists anywhere in the full legal parameter
domain. There is no clamping of negative equity.

## 2. Independent finite stopping problem

For numerical diagnosis only, fix the bond-pricing boundary `b0` *before*
computing its cashflow `f(V;b0)`, including the extension below `b0`
defined by the fixed recovery value. On a truncated log-asset interval,
solve the **different, frozen-cashflow** obstacle problem

    max{0.5*sigma**2 * W_xx + (r-payout-0.5*sigma**2)*W_x
        -r*W + f(b0*exp(x);b0), -W} = 0.

The finite grid uses nonnegative Markov jump coefficients, upwinds when
central differencing would violate monotonicity, solves each active-set
tridiagonal system, and reports the discrete complementarity residual.
Zero is imposed at the lower truncation point. At the upper point, the
test supplies the **full finite-maturity asymptote**, including survival
principal:

    d_infty = c/q + exp(-q*m)*(principal/m-c/q)
    K_infty = (1-tax_shield)*coupon + principal/m - d_infty
    W_upper ~= V_upper - K_infty/r.

Leaving out the surviving principal term gives a materially wrong upper
boundary and misleading numerical comparisons. The upper truncation
itself is not certified; study the high-boundary sensitivity explicitly.

The computed nonnegative value does **not** reprice the bond when the
optimal stopping boundary moves. It is not a self-consistent HX equilibrium,
a neuron, a proof of full-domain nonnegativity, or proof of stable fp32/fp16
and gradient kernels.

## 3. Reproduction and observed local development evidence

At the stacked repository branch, with Python, NumPy and SciPy:

    python -m unittest -v experiments.hcsn_hx_unified_v3.test_obstacle

During local development, five tests passed on Python 3.13.5,
NumPy 2.3.5, SciPy 1.17.0. The local fixture replicated the needed
upstream HX reference functions, **not** a byte-identical Git checkout.
Remote exact-head integration and independently measured runtime have
not been executed here; the tests in this PR are executable source.

Tests cover: (a) an unrelated analytic perpetual abandonment solution
with refined meshes, (b) all 128 finite policies of a nine-node upwind
problem versus Howard iteration, (c) invalid domains, (d) the retained
HX negative-equity counterexample, and (e) HX finite-grid convergence
with the correct finite-maturity upper asymptote.

Selected *local diagnostic* values (not global proofs):

| HX inputs | Algebraic b | Boundary cashflow | Gate |
| --- | ---: | ---: | --- |
| Default `HX()` | 64.6251766753 | -11.6736916972 | LOCAL_NECESSARY_ONLY |
| `sale_fraction=0.2` | 101.3240286091 | +0.4369294410 | REJECT_NEGATIVE_CONTINUATION_EQUITY |

At 1.01*b with sale_fraction=0.2, original A7 equity is
about -0.0004892856; the 513-node frozen-price obstacle gives
about +0.1596573. The latter **does not repair** the HX coupled
free-boundary equation; it shows the fixed-boundary no-stop
continuation is incompatible with the free-stopping obstacle.

For default HX at 2*b, the 513-node fixed-price obstacle differs
from A7 by +0.0077066; the 129-node error is +0.0827216.
These are finite-domain convergence observations, not rigorous
interval estimates or all-domain derivative bounds.

## 4. Explicit blocked gates

- **P0**: no global sign/obstacle classification, self-consistent
  free-boundary equilibrium, interval proof, extreme-parameter
  convergence bounds, exact-head native fp32/fp16 or gradients.
- **P1**: no new training, matched slopes/parameters or independent
  confirmatory mechanism wins. Parent #4255's 0/4 registered gains
  and CPU disadvantages remain negative evidence.
- **P2/P3**: no new continuous sampled-spike, overwrite/MQAR, or paired
  text-image-audio-video success claims.
- **P4**: no Rust/GPU kernels, hardware/energy/p99/4096-Cell or real
  power-loss recovery measurement.
- **P5**: no scaling authorization; fair data/token/FLOP/total
  compute superiority must be established first.

**Next executable mathematical gate**: independently solve the *coupled*
equity/bond obstacle with an explicit outer boundary fixed point,
certify truncation and conditioning across a frozen parameter
suite, use interval bounds on the boundary sign, and reject
parameter regimes with no admissible equilibrium. Do not change
research negatives into successes or introduce production authority.
