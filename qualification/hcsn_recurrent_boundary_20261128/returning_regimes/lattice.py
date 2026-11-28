"""Finite-horizon optimal stopping with recurrent liquidity regimes and rolling debt."""
from pathlib import Path
import sys
from dataclasses import dataclass, replace
import numpy as np
from scipy.linalg import expm, expm_frechet
from scipy.special import log_ndtr

sys.path.insert(0, str(Path(__file__).resolve().parents[2] /
                       "hcsn_sustained_20261128" / "resolvent"))
from closed_form import Contract, Prices


@dataclass
class Panel:
    assets: np.ndarray
    equity: np.ndarray
    bond: np.ndarray
    loss: np.ndarray
    hit: np.ndarray
    walls: np.ndarray
    grid_brackets: np.ndarray
    equity_gradient: np.ndarray
    loss_gradient: np.ndarray
    hit_gradient: np.ndarray
    wall_gradient: np.ndarray
    policy: np.ndarray


def hit_weights(x, horizons, discount, p):
    """Discounted hits at the stationary tail, vectorized over time and x."""
    var = p.sigma**2
    mu = p.r - p.payout - var / 2
    speed = np.sqrt(mu**2 + 2 * discount * var)
    w = p.sigma * np.sqrt(horizons)
    return sum(np.exp(-(mu+s)*x/var + log_ndtr((s*horizons-x)/w))
               for s in (speed, -speed))


def tail(assets, steps, p, premia, prices):
    """At H the current liquidity state becomes permanent; closed-form terminal values."""
    dt = p.maturity / steps
    horizons = np.arange(1, steps+1)[:, None] * dt
    par, coupon = p.principal / p.maturity, p.coupon / p.maturity
    equity = np.empty((2, len(assets)))
    debt = np.empty((2, steps+1, len(assets)))
    hit = np.zeros_like(debt)
    for s, price in enumerate(prices):
        x = np.log(assets / price.boundary)
        live = x > 0
        equity[s] = np.array([price.equity(v) for v in x])
        q = p.r + premia[s]
        f = hit_weights(x[None, live], horizons, 0, p)
        g = hit_weights(x[None, live], horizons, q, p)
        price_live = (coupon/q + np.exp(-q*horizons)*(par-coupon/q)*(1-f)
                      + (p.recovery*price.boundary/p.maturity-coupon/q)*g)
        debt[s, 0] = np.where(live, par, p.recovery*assets/p.maturity)
        debt[s, 1:][:, live] = price_live
        debt[s, 1:][:, ~live] = p.recovery*assets[~live]/p.maturity
        hit[s, 1:][:, live] = f
        hit[s, :, ~live] = 1.
    # Future no-default price, needed to isolate credit from the liquidity discount.
    qs = p.r + np.asarray(premia)[:, None]
    times = np.arange(steps+1)[None, :] * dt
    safe = coupon/qs + np.exp(-qs*times)*(par-coupon/qs)
    return equity, debt, hit, safe


def spatial(values, up, middle, down):
    # Endpoint clamping is a numerical truncation; checks enlarge the domain.
    result = middle * values
    result[..., :-1] += up * values[..., 1:]
    result[..., -1] += up * values[..., -1]
    result[..., 1:] += down * values[..., :-1]
    result[..., 0] += down * values[..., 0]
    return result


def mix(matrix, values):
    return np.stack((matrix[0, 0]*values[0] + matrix[0, 1]*values[1],
                     matrix[1, 0]*values[0] + matrix[1, 1]*values[1]))


def solve(*, steps=48, years=2., rates=(.7, .35), premia=(.01, .05),
          log_half_width=2.5, p=Contract(), gradients=True):
    """Compute the two-state panel and derivative in the low-to-high switch rate.

    Exact matrix exponentials integrate the exogenous regime and liquidity discount
    between decision dates. Credit default is monitored only on the decision grid.
    """
    dt = p.maturity / steps
    periods = round(years/dt)
    if steps < 2 or periods < 1 or abs(periods*dt-years)>1e-10:
        raise ValueError("require an integral number of positive decision steps")
    if min(rates) < 0 or len(premia)!=2 or min(premia)<0:
        raise ValueError("require two nonnegative premia and transition rates")
    q = np.array([[-rates[0], rates[0]], [rates[1], -rates[1]]])
    direction = np.array([[-1., 1.], [0., 0.]])
    bond_matrix = q - np.diag(p.r + np.asarray(premia))
    move, dmove = expm_frechet(dt*q, dt*direction)
    discount, ddiscount = expm_frechet(dt*bond_matrix, dt*direction)
    # Integrate the coupon before the next decision; solve M J = exp(M dt)-I.
    ones = np.ones(2)
    coupon = p.coupon / p.maturity
    accrual = coupon * np.linalg.solve(bond_matrix, (discount - np.eye(2)) @ ones)
    daccrual = np.linalg.solve(bond_matrix, coupon * ddiscount@ones - direction@accrual)
    prices = [Prices(replace(p, premium=x)) for x in premia]
    dx = p.sigma * np.sqrt(3*dt)
    half = int(np.ceil(log_half_width / dx))
    assets = 70*np.exp(dx * np.arange(-half, half+1))
    mu = p.r - p.payout - p.sigma**2 / 2
    second = (p.sigma**2*dt+(mu*dt)**2)/dx**2
    up, down, middle = (second+mu*dt/dx)/2, (second-mu*dt/dx)/2, 1-second
    if min(up, down, middle)<0:
        raise ValueError("nonpositive transition stencil")
    def shift(x):
        return spatial(x, up, middle, down)
    equity, debt, hit, safe = tail(assets, steps, p, premia, prices)
    dequity, ddebt, dhit, dsafe = (np.zeros_like(a) for a in (equity, debt, hit, safe))
    par, recovery = p.principal / p.maturity, p.recovery*assets/p.maturity
    equity_discount = np.exp(-p.r*dt)
    flow_discount = -np.expm1(-p.r*dt)/p.r
    asset_payout = -np.expm1(-p.payout*dt)*assets
    policies = []
    for _ in range(periods):
        next_debt, next_hit, next_equity = shift(debt[:, :-1]), shift(hit[:, :-1]), shift(equity)
        cont_debt = mix(discount, next_debt) + accrual[:, None, None]
        cont_hit = mix(move, next_hit)
        cont_safe = mix(discount, safe[:, :-1]) + accrual[:, None]
        continuation = (asset_payout + flow_discount*(cont_debt[:, -1]-par-(1-p.tax)*p.coupon)
                        + equity_discount*mix(move, next_equity))
        live = continuation > 0.
        policies.append(live)
        if gradients:
            dcont_debt = (mix(ddiscount, next_debt) + mix(discount, shift(ddebt[:, :-1]))
                          + daccrual[:, None, None])
            dcont_hit = mix(dmove, next_hit) + mix(move, shift(dhit[:, :-1]))
            dcont_safe = (mix(ddiscount, safe[:, :-1]) + mix(discount, dsafe[:, :-1])
                          + daccrual[:, None])
            dcontinuation = (flow_discount*dcont_debt[:, -1]
                             + equity_discount*(mix(dmove, next_equity) + mix(move, shift(dequity))))
            dequity = np.where(live, dcontinuation, 0.)
            ddebt[:, 1:] = np.where(live[:, None, :], dcont_debt, 0.)
            dhit[:, 1:] = np.where(live[:, None, :], dcont_hit, 0.)
            dsafe[:, 1:] = dcont_safe
        equity = np.maximum(continuation, 0.)
        debt[:, 0] = np.where(live, par, recovery)
        debt[:, 1:] = np.where(live[:, None, :], cont_debt, recovery)
        hit[:, 0] = ~live
        hit[:, 1:] = np.where(live[:, None, :], cont_hit, 1.)
        safe[:, 1:] = cont_safe
    walls, brackets, derivatives = [], [], []
    for s in range(2):
        crossings = np.flatnonzero(np.diff(live[s].astype(int)))
        if len(crossings)!=1 or not live[s,-1]:
            raise ValueError("policy is not a one-threshold rule on this grid")
        i = crossings[0]
        lo, hi = continuation[s,i:i+2]
        span = assets[i+1]-assets[i]
        walls.append(assets[i] - span*lo/(hi-lo))
        brackets.append(assets[i:i+2])
        if gradients:
            dlo, dhi = dcontinuation[s,i:i+2]
            derivatives.append(span*(lo*dhi-hi*dlo)/(hi-lo)**2)
    return Panel(assets, equity, debt[:, -1], safe[:, -1, None]-debt[:, -1],
                 hit[:, -1], np.array(walls), np.array(brackets), dequity,
                 dsafe[:, -1, None]-ddebt[:, -1], dhit[:, -1], np.array(derivatives),
                 np.asarray(policies)[::-1])
