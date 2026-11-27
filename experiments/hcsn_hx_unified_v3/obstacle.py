"""Fail-closed local HX viability and an independent frozen-cashflow obstacle oracle.

The finite-grid oracle freezes the bond-pricing boundary before solving the
stopping problem. It is NOT a self-consistent He--Xiong equilibrium, an all-domain
certificate, a neuronal value function, or an execution-authority decision.
"""

from bisect import bisect_left
from dataclasses import dataclass
import math
from typing import Callable


@dataclass(frozen=True)
class CandidateAudit:
    status: str
    boundary_cashflow: float
    sign_tolerance: float
    minimum_sampled_equity: float
    worst_asset_ratio: float
    certified: bool = False


def financial_cashflow(p, asset: float, reference_boundary: float) -> float:
    """Earnings in the financial fixed-barrier ODE, not neural utility."""
    from .hx import bond_value
    return math.fsum((p.payout * asset, -(1 - p.tax_shield) * p.coupon,
                      bond_value(p, asset, p.maturity, reference_boundary),
                      -p.per_bond_principal))


def audit_candidate(p, boundary: float, *, ratios=(1.00001, 1.001, 1.01,
                                                    1.1, 1.5, 2., 4.)) -> CandidateAudit:
    """Necessary curvature test and finite observation; never returns PASS.

    Smooth pasting implies E_x(0)=E(0)=0 and
    E_xx(0+)=-2*f(boundary)/sigma**2. Positive f(boundary) therefore
    contradicts continuation nonnegativity locally. Negative f is necessary
    but does not establish global admissibility.
    """
    from .hx import equity_closed
    if not math.isfinite(boundary) or boundary <= 0:
        raise ValueError('Candidate requires a finite positive boundary')
    ratios = tuple(ratios)
    if not ratios or any(not math.isfinite(q) or q <= 1 for q in ratios):
        raise ValueError('Finite asset ratios must be strictly greater than one')
    terms = (p.payout * boundary, -(1 - p.tax_shield) * p.coupon,
             p.recovery * boundary / p.maturity, -p.per_bond_principal)
    flow = math.fsum(terms)
    scale = max(1., *(abs(t) for t in terms), sum(abs(t) for t in terms))
    tolerance = 128 * math.ulp(scale)
    pairs = [(q, equity_closed(p, boundary * q, boundary)) for q in ratios]
    if any(not math.isfinite(v) for _, v in pairs):
        raise ArithmeticError('Nonfinite sampled equity')
    worst_ratio, minimum = min(pairs, key=lambda a: a[1])
    if flow > tolerance:
        status = 'REJECT_POSITIVE_BOUNDARY_CASHFLOW'
    elif abs(flow) <= tolerance:
        status = 'UNRESOLVED_ZERO_CURVATURE'
    else:
        status = 'LOCAL_NECESSARY_ONLY'
    if minimum < -tolerance:
        status = 'REJECT_NEGATIVE_CONTINUATION_EQUITY'
    return CandidateAudit(status, flow, tolerance, minimum, worst_ratio)


@dataclass(frozen=True)
class ObstacleGrid:
    assets: tuple[float, ...]
    values: tuple[float, ...]
    max_complementarity_residual: float
    policy_iterations: int
    last_zero_asset: float
    """An approximate policy/mesh witness, never a proof of continuum optimality."""

    def at(self, asset: float) -> float:
        if not math.isfinite(asset) or not self.assets[0] <= asset <= self.assets[-1]:
            raise ValueError('Asset outside computed grid')
        i = bisect_left(self.assets, asset)
        if i == 0:
            return self.values[0]
        if i == len(self.assets):
            return self.values[-1]
        lo, hi = self.assets[i-1], self.assets[i]
        # Grid is uniform in log asset, not in asset units.
        w = math.log(asset/lo) / math.log(hi/lo)
        return self.values[i-1] * (1-w) + self.values[i] * w


def _tridiagonal(lower, diagonal, upper, rhs):
    """Thomas elimination; strict diagonally dominant M-matrix rows."""
    n = len(rhs)
    c = [0.] * n
    d = [0.] * n
    for i in range(n):
        den = diagonal[i] - (lower[i] * c[i-1] if i else 0.)
        if not math.isfinite(den) or den <= 0:
            raise ArithmeticError('Nonpositive diagonal pivot')
        c[i] = upper[i] / den
        d[i] = (rhs[i] - (lower[i] * d[i-1] if i else 0.)) / den
    out = [0.] * n
    out[-1] = d[-1]
    for i in range(n-2, -1, -1):
        out[i] = d[i] - c[i] * out[i+1]
    return out


def solve_frozen_obstacle(*, scale: float, log_min: float, log_max: float,
                          nodes: int, rate: float, log_drift: float,
                          volatility: float, cashflow: Callable[[float], float],
                          upper_value: float, max_iterations: int = 200) -> ObstacleGrid:
    """Solve max{L W-rW+f, -W}=0 using a monotone tri-diagonal scheme.

    The lower Dirichlet boundary is zero; the upper Dirichlet value must be
    supplied independently and is NOT certified by this solver. A centered
    generator is used only while its Markov off-diagonals stay nonnegative;
    otherwise positive-rate upwinding is used. Howard policy iteration solves
    the finite linear-complementarity problem to a measured residual.
    """
    vals = (scale, log_min, log_max, rate, log_drift, volatility, upper_value)
    if (not all(math.isfinite(z) for z in vals) or scale <= 0 or rate <= 0
            or volatility <= 0 or nodes < 9 or log_max <= log_min
            or upper_value < 0 or max_iterations < 1):
        raise ValueError('Invalid finite obstacle inputs')
    h = (log_max - log_min) / (nodes - 1)
    assets = [scale * math.exp(log_min + h * i) for i in range(nodes)]
    if any(not math.isfinite(v) or v <= 0 for v in assets):
        raise ValueError('Asset mesh overflows or underflows')
    f = [float(cashflow(v)) for v in assets]
    if any(not math.isfinite(v) for v in f):
        raise ValueError('Nonfinite cashflow on obstacle mesh')
    diffusion = .5 * volatility**2 / h**2
    ql = diffusion - log_drift/(2*h)
    qr = diffusion + log_drift/(2*h)
    if min(ql, qr) < 0:
        ql = diffusion + max(0., -log_drift)/h
        qr = diffusion + max(0., log_drift)/h
    diagonal_cont = rate + ql + qr
    active = [False] + [v > 0 for v in f[1:-1]] + [False]
    u = [0.] * nodes
    u[-1] = upper_value
    for it in range(1, max_iterations+1):
        low = [0.] * nodes
        diag = [1.] * nodes
        high = [0.] * nodes
        rhs = [0.] * nodes
        rhs[-1] = upper_value
        for i in range(1,nodes-1):
            if active[i]:
                low[i], diag[i], high[i], rhs[i] = -ql, diagonal_cont, -qr, f[i]
        u = _tridiagonal(low, diag, high, rhs)
        next_active = [False] + [f[i]+ql*u[i-1]+qr*u[i+1] > 0
                                  for i in range(1, nodes-1)] + [False]
        if active == next_active:
            break
        active = next_active
    else:
        raise ArithmeticError('Obstacle policy iteration did not converge')
    residual = 0.
    for i in range(1,nodes-1):
        cont = f[i] + ql*(u[i-1]-u[i]) + qr*(u[i+1]-u[i])-rate*u[i]
        residual = max(residual, abs(max(cont, -u[i])))
    if any(z < -1e-9 * max(1., upper_value) for z in u):
        raise ArithmeticError('Obstacle solver returned negative stopping value')
    last_zero = max((i for i in range(nodes-1) if u[i] <= 1e-11), default=0)
    return ObstacleGrid(tuple(assets), tuple(u), residual, it, assets[last_zero])
