"""Research-only global verification argument for a *scalar* regenerative QVI.

This does NOT certify the coupled He--Xiong financial boundary, a finite neural
state grid, learned coefficients, or floating-point/GPU production inference.

For dX=mu dt+sigma dW, reward X-K, reset r<K after deterministic dead time
T>=0 and discount rho>0, let k>0 solve mu*k+sigma**2*k**2/2=rho.
The unique t in (0,1) with h=-log(1-t)-t, h=rho*T+k*(K-r)>0,
sets b=K+t/k and q=exp(-h-t)=1-t. The candidate value is
  V(x)=exp(k*(x-b))/k                   for x<b
  V(x)=x-K+q/k                         for x>=b.

This gives an ALL-STATE analytic QVI check, not a finite sampled residual:
  V(x)-(x-K+q/k)=(exp(-u)-1+u)/k >=0, u=k*(b-x)>0;
  (L-rho)V=0 for x<b by the characteristic equation;
  (L-rho)V=mu-rho*V <= -sigma**2*k/2 <0 for x>=b.
At the threshold V and V' agree; reset/refractory renewals contract by q<1.
The discounted linear-growth transversality condition holds for Brownian X.
The verification theorem therefore supports this *ideal stationary scalar*
optimal stopping/renewal problem; nothing is asserted about coupled HX assets.

Decimal is an independent *numerical check* of the symbolic premises. It is
not directed-rounding interval arithmetic. Nonrepresentable/dangerous f64
parameters are refused rather than counted as successes.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
import math


@dataclass(frozen=True)
class ScalarCase:
    drift: float
    diffusion: float
    discount: float
    cost: float
    reset: float
    refractory: float


@dataclass(frozen=True)
class ScalarGlobalQviResult:
    kappa: float
    boundary: float
    t: float
    renewal_ratio: float
    generator_upper_bound: float
    observed_boundary_checked: bool
    scope: str = 'ANALYTIC_IDEAL_SCALAR_ONLY_NOT_PRODUCTION'


def _input_check(p: ScalarCase) -> None:
    if not all(math.isfinite(x) for x in (
        p.drift, p.diffusion, p.discount, p.cost, p.reset, p.refractory
    )):
        raise ValueError('Nonfinite scalar problem parameter')
    if not (p.diffusion > 0 and p.discount > 0 and
            p.reset < p.cost and p.refractory >= 0):
        raise ValueError('Invalid scalar problem domain')


def audit_scalar_global_qvi(
    p: ScalarCase, *, observed_boundary: float | None = None,
) -> ScalarGlobalQviResult:
    """Fail-closed Decimal witness for an exact symbolic *scalar* QVI theorem.

    Only accepts 1e-60 <= h <= 30, strictly distinguishable f64 boundary,
    resolved kappa/reward and an optional observed production-model boundary
    within 8 ULP AND 1e-9 of its normalized displacement. These are an
    intentionally narrow numerical admission domain, NOT full-domain proof
    of the existing binary64 implementation or an interval guarantee.
    """
    _input_check(p)
    d = Decimal.from_float
    with localcontext() as ctx:
        ctx.prec = 160
        mu, sigma, rho = d(p.drift), d(p.diffusion), d(p.discount)
        cost, reset, duration = d(p.cost), d(p.reset), d(p.refractory)
        discriminant = (mu * mu + 2 * rho * sigma * sigma).sqrt()
        if mu >= 0:
            k = 2 * rho / (discriminant + mu)
        else:
            k = (discriminant - mu) / (sigma * sigma)
        if k <= 0:
            raise ArithmeticError('Unresolved positive characteristic root')
        h = rho * duration + k * (cost - reset)
        if not Decimal('1e-60') <= h <= Decimal(30):
            raise ArithmeticError('Renewal loss outside audited precision domain')

        # Solve the ORIGINAL exponential smooth-fit equation, not the main
        # Lambert-W or power-series inverse. Safeguard against the extraneous
        # zero root introduced by binary64 cancellation near h=0.
        lo, hi = Decimal(0), Decimal(1)
        t = (2 * h).sqrt() if h < Decimal('0.05') else 1 - (-(h + 1)).exp()
        converged = False
        for _ in range(128):
            exp_term = (-(h + t)).exp()
            residual = t + exp_term - 1
            if residual > 0:
                hi = t
            else:
                lo = t
            if abs(residual) <= h * Decimal('1e-58'):
                converged = True
                break
            slope = 1 - exp_term
            candidate = t - residual / slope if slope > 0 else (lo + hi) / 2
            t = candidate if lo < candidate < hi else (lo + hi) / 2
        if not converged or not 0 < t < 1:
            raise ArithmeticError('Independent smooth-fit root unresolved')
        q = (-(h + t)).exp()
        if abs(t + q - 1) > h * Decimal('1e-57'):
            raise ArithmeticError('Regenerative contraction identity unresolved')
        b = cost + t / k
        if not (b > cost and b > reset):
            raise ArithmeticError('Nonpositive threshold reward')

        # Exact-sign analytic predicates; these do not need a state grid.
        upper = -(sigma * sigma * k / 2)
        if not (0 < q < 1 and upper < 0):
            raise ArithmeticError('Global-QVI sign condition not established')
        k64, b64, t64, q64, upper64 = map(
            float, (k, b, t, q, upper)
        )
        values = (k64, b64, t64, q64, upper64)
        if not all(map(math.isfinite, values)):
            raise ArithmeticError('Global QVI witness not representable in f64')
        if not (k64 > 0 and b64 > p.cost and 0 < t64 < 1 and
                0 < q64 < 1 and upper64 < 0):
            raise ArithmeticError('Global QVI witness collapsed in f64')
        displacement = b - cost
        # Ensure the *actual* float encoding can resolve a meaningful boundary.
        if d(math.ulp(b64)) * 16 >= displacement * Decimal('1e-5'):
            raise ArithmeticError('Boundary displacement lacks f64 resolution')
        if d(math.ulp(k64)) > d(k64) * Decimal('1e-9'):
            raise ArithmeticError('Characteristic exponent lacks f64 resolution')
        if observed_boundary is not None:
            if not (math.isfinite(observed_boundary) and observed_boundary > p.cost):
                raise ArithmeticError('Observed threshold not finite and positive')
            error = abs(d(observed_boundary) - b)
            ulp_budget = d(math.ulp(observed_boundary)) * 8
            rel_budget = displacement * Decimal('1e-9')
            if error > ulp_budget or error > rel_budget:
                raise ArithmeticError('Observed threshold disagrees with Decimal root')
        return ScalarGlobalQviResult(
            kappa=k64, boundary=b64, t=t64, renewal_ratio=q64,
            generator_upper_bound=upper64,
            observed_boundary_checked=observed_boundary is not None,
        )
