"""Reproduce the He–Xiong Table I operator check. Requires Python 3 and SciPy.

Run python independent/hx_crosscheck.py from the parent directory.
The default output is hx_crosscheck.json alongside this script.
"""

import argparse
import json
from dataclasses import asdict, dataclass
from math import exp, expm1, log, pi, sqrt
from pathlib import Path

from scipy.integrate import quad
from scipy.special import log_ndtr, ndtr


@dataclass(frozen=True)
class Parameters:
    rate: float = 0.08
    payout: float = 0.02
    volatility: float = 0.23
    tax_benefit: float = 0.27
    recovery: float = 0.60
    transaction_cost: float = 0.01
    maturity: float = 1.0
    coupon: float = 6.39
    principal: float = 61.68


def integrate(fn, low, high):
    return quad(fn, low, high, epsabs=1e-12, epsrel=1e-12)[0]


class StationaryFirm:
    """Constant-coefficient regime, as defined in equations (5)–(12)."""

    def __init__(self, params, shock_intensity):
        self.params = params
        r, sigma = params.rate, params.volatility
        self.mu = r - params.payout - sigma**2 / 2
        self.q = r + shock_intensity * params.transaction_cost
        self.a = self.mu / sigma**2
        self.z = sqrt(self.a**2 + 2 * r / sigma**2)
        self.z_hat = sqrt(self.a**2 + 2 * self.q / sigma**2)
        self.eta = self.z - self.a
        self.gamma = self.z + self.a
        self.c = params.coupon / params.maturity
        self.p = params.principal / params.maturity

    def first_passage(self, x):
        """Return (F, G) at horizon m for x=log(V/B), equations (8)–(9)."""
        s, t = self.params.volatility, self.params.maturity
        scale = s * sqrt(t)

        def n(arg):
            return (-x + arg * s**2 * t) / scale

        f = ndtr(n(-self.a)) + exp(-2 * self.a * x + log_ndtr(n(self.a)))
        g = exp((-self.a + self.z_hat) * x + log_ndtr(n(-self.z_hat)))
        g += exp((-self.a - self.z_hat) * x + log_ndtr(n(self.z_hat)))
        return f, g

    def boundary_closed(self):
        """Direct evaluation of Proposition 1, equation (12), at Table I inputs."""
        s, t = self.params.volatility, self.params.maturity
        scale = s * sqrt(t)
        discounted_tail = ndtr(-self.z * scale)

        def small_b(y):
            return exp(-self.q * t) * (
                ndtr(y * scale) - exp(self.params.rate * t) * discounted_tail
            ) / (self.z + y)

        def capital_b(y):
            correction = exp((self.z**2 - y**2) * s**2 * t / 2)
            return (ndtr(y * scale) - correction * discounted_tail) / (self.z + y)

        debt_gap = self.p - self.c / self.q
        annual_cost = (1 - self.params.tax_benefit) * self.params.coupon
        common = capital_b(-self.z_hat) + capital_b(self.z_hat)
        numerator = (annual_cost - expm1(-self.q * t) * debt_gap) / self.eta
        numerator += debt_gap * (small_b(-self.a) + small_b(self.a))
        numerator += self.c / self.q * common
        denominator = self.params.payout / (self.eta - 1)
        denominator += self.params.recovery / t * common
        return numerator / denominator

    def boundary_green(self):
        """Solve U'(0)=0 from the equity ODE using independent quadrature.

        U(x)=E(B exp(x)); eta solves sigma² eta²/2 + mu eta = r.
        U'(0) = (2/sigma²) integral_0^inf exp(-eta y) g_B(y) dy.
        At fixed log-distance y the total cash-flow source g_B is affine in B.
        Integrate the level and exp(y) terms analytically.
        """
        t = self.params.maturity
        debt_gap = self.p - self.c / self.q
        annual_cost = (1 - self.params.tax_benefit) * self.params.coupon
        fi = integrate(lambda y: exp(-self.eta * y) * self.first_passage(y)[0],
                       0, float("inf"))
        gi = integrate(lambda y: exp(-self.eta * y) * self.first_passage(y)[1],
                       0, float("inf"))
        numerator = (annual_cost - expm1(-self.q * t) * debt_gap) / self.eta
        numerator += debt_gap * exp(-self.q * t) * fi + self.c / self.q * gi
        return numerator / (
            self.params.payout / (self.eta - 1) + self.params.recovery / t * gi
        )

    def debt(self, x, boundary):
        f, g = self.first_passage(x)
        t = self.params.maturity
        return (self.c / self.q
                + exp(-self.q * t) * (self.p - self.c / self.q) * (1 - f)
                + (self.params.recovery * boundary / t - self.c / self.q) * g)

    def equity_green(self, v, boundary):
        """Integrate the killed half-line Green kernel for equation (11)."""
        if v <= boundary:
            return 0.0
        x = log(v / boundary)
        eta, gamma = self.eta, self.gamma
        running_payout = self.params.payout * boundary

        def bounded_source(y):
            return (self.debt(y, boundary) - self.p
                    - (1 - self.params.tax_benefit) * self.params.coupon)

        def left_integrand(y):
            weight = exp(-gamma * x) * (exp(gamma * y) - exp(-eta * y))
            return weight * (running_payout * exp(y) + bounded_source(y))

        def right_integrand(y):
            return exp(-eta * y) * bounded_source(y)

        left = integrate(left_integrand, 0, x)
        right = integrate(right_integrand, x, float("inf"))
        right += running_payout * exp((1 - eta) * x) / (eta - 1)
        right_weight = exp(-gamma * x) * expm1((eta + gamma) * x)
        return 2 * (left + right_weight * right) / (
            self.params.volatility**2 * (eta + gamma)
        )

    def risk_gradient(self, v, boundary):
        """Analytic partial F/partial V at fixed parameters, for V>B."""
        x = log(v / boundary)
        s, t = self.params.volatility, self.params.maturity
        scale = s * sqrt(t)
        y1, y2 = (-x - self.mu * t) / scale, (-x + self.mu * t) / scale
        normal_density = exp(-y1**2 / 2) / sqrt(2 * pi)
        return (-2 * normal_density / scale
                - 2 * self.a * exp(-2 * self.a * x) * ndtr(y2)) / v


def check():
    params = Parameters()
    boundary_check = []
    for intensity in (1, 2, 4):
        firm = StationaryFirm(params, intensity)
        direct, green = firm.boundary_closed(), firm.boundary_green()
        x = log(100 / direct)
        boundary_check.append({
            "shock_intensity": intensity, "boundary_eq12": direct,
            "boundary_green": green, "abs_difference": abs(direct - green),
            "one_year_hit_probability_at_V100": firm.first_passage(x)[0],
        })
    firm = StationaryFirm(params, 1)
    baseline = firm.boundary_closed()
    readouts = []
    for v in (baseline, 75.0, 100.0):
        readouts.append({"V": v, "equity_green": firm.equity_green(v, baseline),
                         "one_year_hit_probability": firm.first_passage(log(v / baseline))[0]})
    v, step = 100.0, 1e-4
    hi = firm.first_passage(log((v + step) / baseline))[0]
    lo = firm.first_passage(log((v - step) / baseline))[0]
    exact = firm.risk_gradient(v, baseline)
    central = (hi - lo) / (2 * step)
    slope_checks = [
        {"h": h, "equity_forward_slope": firm.equity_green(baseline + h, baseline) / h}
        for h in (0.1, 0.01, 0.001)
    ]
    if max(row["abs_difference"] for row in boundary_check) > 1e-10:
        raise ArithmeticError("Boundary evaluations disagree")
    if abs(exact - central) > 1e-9:
        raise ArithmeticError("Hit-probability gradients disagree")
    return {
        "paper": "He and Xiong (2012), Journal of Finance, 67(2), 391–430",
        "source": "https://www.princeton.edu/~wxiong/papers/rollover.pdf",
        "parameters_from_table_I": asdict(params), "boundary_check": boundary_check,
        "readouts_at_shock_intensity_1": readouts,
        "risk_gradient_at_V100_shock_intensity_1": {
            "analytic": exact, "central_difference": central, "step": step,
            "abs_difference": abs(central - exact),
        },
        "smooth_pasting_at_shock_intensity_1": slope_checks,
        "scope": "Stationary scalar valuation and risk-neutral first passage. No model training.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_suffix(".json"))
    output = parser.parse_args().output
    output.write_text(json.dumps(check(), indent=2, ensure_ascii=False, allow_nan=False)
                      + "\n", encoding="utf-8")
    print(output)
