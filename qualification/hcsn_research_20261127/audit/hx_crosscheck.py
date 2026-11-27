"""Cross-check a stationary He–Xiong cell at the published Table I parameters.

Source: Zhiguo He and Wei Xiong, Rollover Risk and Credit Risk, J. Finance
67 (2012), 391–430, equations (8)–(12), (A5), (A7).
https://www.princeton.edu/~wxiong/papers/rollover.pdf

Run with Python, NumPy and SciPy: python hx_crosscheck.py
The transformed Green-function integral verifies the equity and boundary
expressions while using the same published bond pricing function. A separate
Brownian-bridge computation checks the first-passage probabilities.
"""
from dataclasses import dataclass, replace
from math import exp, expm1, log, sqrt

import numpy as np
import scipy
from scipy.integrate import quad
from scipy.optimize import brentq
from scipy.special import log_ndtr, ndtr


@dataclass(frozen=True)
class Calibration:
    r: float = 0.08
    payout: float = 0.02
    volatility: float = 0.23
    recovery: float = 0.60
    tax_benefit: float = 0.27
    coupon: float = 6.39
    principal: float = 61.68
    maturity: float = 1.0
    asset: float = 100.0


class HeXiong:
    def __init__(self, calibration, liquidity_premium):
        self.par = calibration
        self.q = calibration.r + liquidity_premium
        self.var = calibration.volatility**2
        self.mu = calibration.r - calibration.payout - self.var / 2
        self.a = self.mu / self.var
        self.z = sqrt(self.a**2 + 2 * calibration.r / self.var)
        self.z_bond = sqrt(self.a**2 + 2 * self.q / self.var)
        self.eta = self.z - self.a
        self.gamma = self.z + self.a
        self.c = calibration.coupon / calibration.maturity
        self.p = calibration.principal / calibration.maturity
        self.discount = exp(-self.q * calibration.maturity)
        self.p_adjusted = self.p - self.c / self.q
        self.fixed_cost = (1 - calibration.tax_benefit) * calibration.coupon
        self.equity_cost = self.fixed_cost + (1 - self.discount) * self.p_adjusted

    def passage(self, x, horizon, discount_parameter):
        """Eq. (8)–(9). Use a for F, z_bond for discounted passage G."""
        y = discount_parameter
        scale = self.par.volatility * sqrt(horizon)
        shift = y * self.var * horizon
        first = -(self.a - y) * x + log_ndtr((-x - shift) / scale)
        second = -(self.a + y) * x + log_ndtr((-x + shift) / scale)
        return exp(first) + exp(second)

    def bond(self, x, boundary):
        horizon = self.par.maturity
        f = self.passage(x, horizon, self.a)
        g = self.passage(x, horizon, self.z_bond)
        recovery_gap = self.par.recovery * boundary / horizon - self.c / self.q
        return self.c / self.q + self.discount * self.p_adjusted * (1 - f) + recovery_gap * g

    def boundary_terms(self):
        """Basis integrals and denominator shared by the Eq. (12) evaluations."""
        m = self.par.maturity
        s = self.par.volatility * sqrt(m)
        tail = ndtr(-self.z * s)

        def little_b(y):
            return self.discount * (ndtr(y*s) - exp(self.par.r*m)*tail) / (self.z+y)

        def big_b(y):
            scale = exp((self.z**2 - y**2)*s**2/2)
            return (ndtr(y*s) - scale*tail) / (self.z+y)

        bs = little_b(-self.a) + little_b(self.a)
        bs_bond = big_b(-self.z_bond) + big_b(self.z_bond)
        denominator = self.par.payout/(self.eta-1) + self.par.recovery/m*bs_bond
        return bs, bs_bond, denominator

    def boundary(self):
        """Eq. (12), retaining the coupon/principal grouping in the paper."""
        bs, bs_bond, denominator = self.boundary_terms()
        numerator = self.equity_cost/self.eta + self.p_adjusted*bs + self.c/self.q*bs_bond
        return numerator / denominator

    def boundary_coefficients(self):
        """Rearrange Eq. (12) into B = beta_c C + beta_p P, holding q,m fixed."""
        bs, bs_bond, denominator = self.boundary_terms()
        m = self.par.maturity
        weight = (1-self.discount)/self.eta + bs
        beta_c = ((1-self.par.tax_benefit)/self.eta + (bs_bond-weight)/(m*self.q))/denominator
        beta_p = weight/(m*denominator)
        return beta_c, beta_p

    def principal_for_risk(self, target, principal_interval):
        """Invert a specified local probability within a chosen admissible interval.

        Require positive principals and an entirely live finite interval where
        0 < B(P) < V. For sigma,t > 0, the distribution of the maximum of
        drifted Brownian motion has positive density at each x>0. Thus F(x)
        decreases strictly from 1 to 0, and any risk between the endpoints
        has a unique solution provided beta_p != 0.
        """
        lo, hi = principal_interval
        if not (0 < target < 1 and 0 < lo < hi):
            raise ValueError("target/interval outside the chosen interior domain")
        beta_c, beta_p = self.boundary_coefficients()
        if beta_p == 0:
            raise ValueError("the principal cannot change the boundary")
        bounds = sorted((beta_c*self.par.coupon + beta_p*lo,
                         beta_c*self.par.coupon + beta_p*hi))
        if not 0 < bounds[0] < bounds[1] < self.par.asset:
            raise ValueError("principal interval must map into the live interior")
        xmin, xmax = (log(self.par.asset/b) for b in reversed(bounds))
        risk = lambda x: self.passage(x, self.par.maturity, self.a)
        if not risk(xmax) <= target <= risk(xmin):
            raise ValueError("requested risk is outside the chosen principal interval")
        margin = brentq(lambda x: risk(x)-target, xmin, xmax, xtol=1e-14)
        boundary = self.par.asset*exp(-margin)
        return (boundary-beta_c*self.par.coupon)/beta_p, boundary

    def equity_closed(self, x, boundary):
        """Direct evaluation of (A5) and (A7) for x=log(V/boundary)."""
        m = self.par.maturity
        s = self.par.volatility * sqrt(m)

        def k_tail(y, exponent):
            logscale = ((exponent - self.a)**2 - y**2)*s**2/2
            fst = exp(logscale-exponent*x) * ndtr((-x + (exponent-self.a)*s**2)/s)
            snd = exp(-(self.a+y)*x) * ndtr((-x + y*s**2)/s)
            return fst - snd

        def full_k(y):
            j = self.gamma
            scale = exp(((j-self.a)**2 - y**2)*s**2/2)
            coeff = ndtr(y*s) - scale*ndtr((j-self.a)*s)
            return coeff*exp(-j*x) + k_tail(y, j)

        def auxiliary(y):
            first = (full_k(y) + k_tail(-y, -self.eta)) / (self.z-y)
            second = (full_k(-y) + k_tail(y, -self.eta)) / (self.z+y)
            return first + second

        decay = exp(-self.gamma*x)
        payout_term = -self.par.payout*boundary*decay / (self.gamma+1)
        net_cost = -self.equity_cost * (1/self.eta - expm1(-self.gamma*x)/self.gamma)
        recovery_gap = self.par.recovery*boundary/m - self.c/self.q
        bond_term = self.discount*self.p_adjusted*auxiliary(self.a) - recovery_gap*auxiliary(self.z_bond)
        return boundary*exp(x) + (payout_term + net_cost + bond_term)/(self.z*self.var)

    def boundary_slope(self, boundary):
        """Right derivative E_x(0) obtained by integrating Eq. (11).

        Remove the exponential payout term from the quadrature analytically.
        Multiplying the log-coordinate ODE by exp(-eta*x) and integrating
        gives E_x(0+) = 2/var times the integral of the discounted source.
        """
        def source(y):
            return exp(-self.eta*y) * (self.bond(y,boundary) - self.fixed_cost - self.p)

        regular = quad(source, 0, np.inf, epsabs=1e-12)[0]
        growing = self.par.payout*boundary/(self.eta-1)
        return 2*(regular + growing)/self.var

    def equity_integral(self, x, boundary):
        """Eq. (11) solved by a killed constant-coefficient Green function.

        Treat the source terms constant in y and proportional to exp(y)
        analytically, then integrate the remaining decaying bond-price term.
        """
        debt_infinity = self.c/self.q + self.discount*self.p_adjusted
        constant_flow = debt_infinity - self.fixed_cost - self.p
        survival_factor = -expm1(-self.gamma*x)
        base = boundary*(exp(x)-exp(-self.gamma*x)) + constant_flow/self.par.r*survival_factor

        def integral_part(y):
            decay_from_zero = exp(-self.gamma*x-self.eta*y)
            if y < x:
                kernel = exp(-self.gamma*(x-y)) - decay_from_zero
            else:
                kernel = exp(self.eta*(x-y)) - decay_from_zero
            return kernel*(self.bond(y, boundary)-debt_infinity)

        left = quad(integral_part, 0, x, epsabs=1e-12)[0]
        right = quad(integral_part, x, np.inf, epsabs=1e-12)[0]
        return base + (left+right)/(self.z*self.var)

    def bridge_estimate(self, x, draws=200_000, seed=2601):
        """Condition on a Gaussian endpoint, integrate the crossing indicator."""
        m = self.par.maturity
        rng = np.random.default_rng(seed)
        y = x + self.mu*m + sqrt(self.var*m)*rng.standard_normal(draws)
        hit_prob = np.exp(-2*x*np.maximum(y,0)/(self.var*m))
        return hit_prob.mean(), hit_prob.std(ddof=1)/sqrt(draws)


def check_local_edit():
    par = Calibration()
    model = HeXiong(par, 0.01)
    beta_c, beta_p = model.boundary_coefficients()
    errors = []
    for coupon, principal in ((6.39, 61.68), (6.0, 67.0), (9.0, 65.0), (8.0, 59.0)):
        direct = HeXiong(replace(par, coupon=coupon, principal=principal), 0.01).boundary()
        errors.append(abs(direct-(beta_c*coupon+beta_p*principal)))
    assert max(errors) < 1e-12
    print("\nLocal inverse edit: change P, hold V, C, m and all other coefficients fixed")
    print(f"beta_C={beta_c:.12f}, beta_P={beta_p:.12f}, max linearity error={max(errors):.4e}")
    interval = (60., 70.)
    def direct_risk(p):
        alternative = HeXiong(replace(par, principal=p), 0.01)
        x = log(par.asset/alternative.boundary())
        return alternative.passage(x, par.maturity, alternative.a)
    print(f"P in {interval}, feasible F in [{direct_risk(interval[0]):.9f}, {direct_risk(interval[1]):.9f}]")
    for target in (0.10, 0.12, 0.18):
        principal, boundary = model.principal_for_risk(target, interval)
        risk = direct_risk(principal)
        print(f"target={target:.3f}, P={principal:.12f}, B={boundary:.12f}, direct F={risk:.14f}")
        assert interval[0] <= principal <= interval[1] and abs(risk-target) < 1e-13
    for target in (0., 0.8, 1.):
        try:
            model.principal_for_risk(target, interval)
        except ValueError as error:
            print(f"target={target:.1f} rejected: {error}")
        else:
            raise AssertionError("expected an infeasible edit to be rejected")


def run():
    print(f"NumPy {np.__version__}, SciPy {scipy.__version__}")
    par = Calibration()
    print(par)
    for premium in (0.01, 0.02):
        hx = HeXiong(par, premium)
        boundary = hx.boundary()
        numerical_boundary = brentq(hx.boundary_slope, 10, 100)
        x = log(par.asset/boundary)
        equity = hx.equity_closed(x, boundary)
        numerical_equity = hx.equity_integral(x, boundary)
        passage = hx.passage(x, par.maturity, hx.a)
        discounted = hx.passage(x, par.maturity, hx.z_bond)
        mc, standard_error = hx.bridge_estimate(x)
        step = 1e-5
        f = lambda distance: hx.passage(distance, par.maturity, hx.a)
        right_slope = (-3*f(0)+4*f(step)-f(2*step))/(2*step)

        print(f"\nLiquidity premium = {premium:.2f}")
        print(f"Boundary, Eq. (12)       {boundary:.12f}")
        print(f"Boundary, Eq. (11) root  {numerical_boundary:.12f}")
        print(f"E(V=100), (A7)           {equity:.12f}")
        print(f"E(V=100), Eq. (11)       {numerical_equity:.12f}")
        print(f"E at boundary            {hx.equity_closed(0,boundary):.4e}")
        print(f"E_x(0+), Eq. (11)        {hx.boundary_slope(boundary):.4e}")
        print(f"One-year F               {passage:.12f}")
        print(f"One-year G               {discounted:.12f}")
        print(f"One-sided F_x(0+)        {right_slope:.8f}")
        print(f"Brownian bridge MC F     {mc:.9f} (SE {standard_error:.9f}, n=200000, seed=2601)")
        print(f"Checked log margins      0.001, 0.1, log(100/B), 1")
        errors = [abs(hx.equity_closed(v,boundary)-hx.equity_integral(v,boundary))
                  for v in (0.001, 0.1, x, 1.0)]
        print(f"Max equity difference    {max(errors):.4e}")
        assert abs(boundary - numerical_boundary) < 1e-9
        assert abs(hx.equity_closed(0, boundary)) < 1e-10
        assert abs(hx.boundary_slope(boundary)) < 1e-8
        assert max(errors) < 1e-9
        assert abs(mc-passage) < 4*standard_error
    check_local_edit()


if __name__ == "__main__":
    run()
