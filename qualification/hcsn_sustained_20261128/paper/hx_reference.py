"""Independent scalar reference for He–Xiong Table II and fixed-wall event counts.

Run this file with Python, NumPy and SciPy to regenerate the JSON report. The
financial quadrature uses the rounded Table I contract throughout. The renewal
model adds an explicit reset and refractory time to a separate physical process.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math

import numpy as np
from scipy.integrate import quad, solve_ivp
from scipy.optimize import brentq
from scipy.special import erfcx, ndtr


def hit(distance, time, drift, sigma, discount=0.):
    """E[exp(-discount*tau); tau<=time] for the first hit of zero.

    An exponential tilt gives a certain-hit, inward-drift CDF multiplied
    by its infinite-horizon Laplace transform. erfcx eliminates the product
    of a large exponential and a small normal tail in the reflected term.
    """
    if not all(map(math.isfinite, (distance, drift, sigma, discount))):
        raise ValueError("finite distance, drift, volatility and discount required")
    if math.isnan(time) or time < 0 or distance < 0 or sigma <= 0 or discount < 0:
        raise ValueError("invalid time, margin, volatility or discount")
    if distance == 0:
        return 1.
    if time == 0:
        return 0.
    speed = math.hypot(drift, sigma * math.sqrt(2 * discount))
    laplace_rate = ((drift + speed) / sigma**2 if drift >= 0
                    else 2 * discount / (speed - drift))
    ever = math.exp(-distance * laplace_rate)
    if math.isinf(time):
        return ever
    width = sigma * math.sqrt(time)
    z = (speed * time - distance) / width
    positive_tail = (speed * time + distance) / width
    reflected = .5 * math.exp(-.5 * z * z) * erfcx(positive_tail / math.sqrt(2))
    return ever * (ndtr(z) + reflected)


def paper_row(intensity):
    """Recompute the BB, one-year contract from the rounded Table I inputs."""
    if not math.isfinite(intensity) or intensity < 0:
        raise ValueError("liquidity shock intensity must be finite and nonnegative")
    rate, payout, sigma, tax, recovery = .08, .02, .23, .27, .60
    maturity, coupon, principal, initial = 1., 6.39, 61.68, 100.
    discount = rate + .01 * intensity
    drift = rate - payout - sigma**2 / 2
    eta = 2 * rate / (math.hypot(drift, sigma * math.sqrt(2 * rate)) + drift)
    coupon_unit = coupon / maturity
    par_unit = principal / maturity
    par_discounted = math.exp(-discount * maturity) * (par_unit - coupon_unit / discount)

    def integral(q):
        return quad(lambda x: math.exp(-eta*x) * hit(x, maturity, drift, sigma, q),
                    0, np.inf, epsabs=1e-13, epsrel=1e-12)[0]

    f_int, g_int = integral(0.), integral(discount)
    net_cost = ((1 - tax) * coupon + par_unit - coupon_unit / discount) / eta
    boundary = ((net_cost - par_discounted * (1 / eta - f_int)
                 + coupon_unit / discount * g_int)
                / (payout / (eta - 1) + recovery / maturity * g_int))

    def bond(x):
        f = hit(x, maturity, drift, sigma)
        g = hit(x, maturity, drift, sigma, discount)
        return (coupon_unit / discount + par_discounted * (1 - f)
                + (recovery * boundary / maturity - coupon_unit / discount) * g)

    def cash_flow(x):
        return (payout * boundary * math.exp(x) - (1 - tax) * coupon
                + bond(x) - par_unit)

    def ode(x, state):
        equity, slope = state
        return slope, 2 * (rate * equity - drift * slope - cash_flow(x)) / sigma**2

    x = math.log(initial / boundary)
    if x <= 0:
        raise ValueError("published live-firm comparison requires V0 > boundary")
    sol = solve_ivp(ode, (0, x), (0., 0.), rtol=1e-11, atol=1e-13)
    if not sol.success:
        raise ArithmeticError(sol.message)
    price = bond(x)
    def price_minus_observed(yield_rate):
        return (coupon_unit * -math.expm1(-yield_rate * maturity) / yield_rate
                + par_unit * math.exp(-yield_rate * maturity) - price)
    bond_yield = brentq(price_minus_observed, .001, .8)
    f_right = hit_gradient(0., maturity, drift, sigma)[0]
    return dict(intensity=intensity, boundary=boundary, equity_at_100=sol.y[0, -1],
                one_year_passage=hit(x, maturity, drift, sigma), bond_at_100=price,
                spread_bps=10000 * (bond_yield - rate),
                right_risk_log_slope=f_right, right_equity_log_curvature=-2 * cash_flow(0) / sigma**2)


def hit_gradient(x, t, mu, sigma):
    """Right x derivative and interior t, mu, sigma derivatives for q=0, t>0."""
    if not all(map(math.isfinite, (x, t, mu, sigma))) or x < 0 or t <= 0 or sigma <= 0:
        raise ValueError("expected x>=0, t>0, sigma>0 and finite parameters")
    width = sigma * math.sqrt(t)
    d1, d2 = (-x-mu*t) / width, (-x+mu*t) / width
    phi = math.exp(-.5 * d1*d1) / math.sqrt(2 * math.pi)
    if mu < 0:
        refl = .5 * math.exp(-.5 * d1*d1) * erfcx(-d2 / math.sqrt(2))
    else:
        refl = math.exp(-2 * mu*x / sigma**2) * ndtr(d2)
    dx = -2 * phi / width - 2 * mu*refl / sigma**2
    dt = x * phi / (t * width)
    dmu = -2 * x * refl / sigma**2
    dsigma = 2 * x * phi / (sigma * width) + 4 * mu*x*refl / sigma**3
    return dx, dt, dmu, dsigma


@dataclass(frozen=True)
class Renewal:
    initial: float = .2
    reset: float = .2
    lag: float = .05
    drift: float = .03355
    sigma: float = .23

    def __post_init__(self):
        if not all(map(math.isfinite, vars(self).values())):
            raise ValueError("finite renewal parameters required")
        if min(self.initial, self.reset, self.lag, self.sigma) <= 0:
            raise ValueError("positive initial and reset distance, lag and sigma required")

    def count_and_gradient(self, time):
        """Return expected count and derivatives in order initial, reset, lag, drift, sigma, time."""
        if not math.isfinite(time) or time < 0:
            raise ValueError("finite nonnegative time required")
        terms, derivative = [], np.zeros(6)
        for j in range(math.ceil(time / self.lag)):
            t = time - j * self.lag
            if t <= 0:
                break
            x = self.initial + j * self.reset
            terms.append(hit(x, t, self.drift, self.sigma))
            dx, dt, dmu, dsig = hit_gradient(x, t, self.drift, self.sigma)
            derivative += (dx, j*dx, -j*dt, dmu, dsig, dt)
        return math.fsum(terms), derivative

    def long_run(self):
        """Total expectation and limiting firing rate for a constant physical drift."""
        if self.drift > 0:
            p0 = hit(self.initial, math.inf, self.drift, self.sigma)
            escape = -math.expm1(-2*self.drift*self.reset / self.sigma**2)
            return p0 / escape, 0.
        rate = 0. if self.drift == 0 else 1 / (self.lag + self.reset / -self.drift)
        return math.inf, rate


def sample_counts(cell, horizons, size, seed):
    """Independent episode simulation using defective inverse-Gaussian waiting times."""
    if size < 2 or not horizons or any(t <= 0 or not math.isfinite(t) for t in horizons):
        raise ValueError("positive finite horizons and at least two samples required")
    rng = np.random.default_rng(seed)
    clock = np.zeros(size)
    counts = np.zeros((len(horizons), size), dtype=np.int64)
    max_time = max(horizons)
    for j in range(math.ceil(max_time / cell.lag)):
        indices = np.flatnonzero(clock < max_time)
        if not len(indices):
            break
        x = cell.initial if j == 0 else cell.reset
        if cell.drift == 0:
            elapsed = (x / (cell.sigma * rng.standard_normal(len(indices))))**2
        else:
            elapsed = rng.wald(x / abs(cell.drift), (x / cell.sigma)**2, len(indices))
            if cell.drift > 0:
                p = math.exp(-2 * cell.drift * x / cell.sigma**2)
                elapsed[rng.random(len(indices)) > p] = math.inf
        clock[indices] += (cell.lag if j else 0.) + elapsed
        for i, end in enumerate(horizons):
            counts[i, indices] += clock[indices] <= end
    return counts


def report():
    cell = Renewal()
    horizons, n, seed = [1., 5., 10.], 300_000, 20261128
    observed = sample_counts(cell, horizons, n, seed)
    rows = []
    for time, counts in zip(horizons, observed):
        expected, grad = cell.count_and_gradient(time)
        rows.append(dict(time=time, expected_count=expected, mc_mean=counts.mean(),
                         mc_se=counts.std(ddof=1)/math.sqrt(n),
                         p_two_events=hit(cell.initial+cell.reset, time-cell.lag, cell.drift, cell.sigma),
                         mc_two_events=(counts >= 2).mean(), gradient=grad.tolist()))
    total, rate = cell.long_run()
    return dict(paper_rows=[paper_row(x) for x in (0,1,2,4)],
                paper_table_II_BB_one_year_bps={"1":330, "2":499.6, "4":853.0},
                renewal=dict(parameters=vars(cell), paths=n, seed=seed,
                             gradient_order=["initial", "reset", "lag", "drift", "sigma", "time"],
                             expected_total=total, asymptotic_rate=rate, rows=rows))


if __name__ == "__main__":
    print(json.dumps(report(), indent=2, allow_nan=False))
