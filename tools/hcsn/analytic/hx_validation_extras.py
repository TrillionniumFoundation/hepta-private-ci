"""Calibration, parameter derivatives and Taylor-overlap audits.

These are numerical consistency checks, not a claim of automatic
differentiation support or of a neural architecture's training performance.
"""

from dataclasses import replace
import math

import numpy as np
from scipy.integrate import quad
from scipy.optimize import brentq

if __package__:
    from .hx_model import HXModel, Parameters
    from .hx_precision import precision_boundary_equity
    from .hx_reference import boundary_from_quadrature, green_equity
else:
    from hx_model import HXModel, Parameters
    from hx_precision import precision_boundary_equity
    from hx_reference import boundary_from_quadrature, green_equity


def validate_calibration():
    """Check rounded Table I inputs against Table II's one-year BB spreads."""
    rows = []
    for intensity, target in [(1., 330.), (2., 499.6), (4., 853.)]:
        model = HXModel(replace(Parameters(), liquidity=.01*intensity))
        x = math.log(100/model.boundary)
        price = float(model.debt(x))
        def yield_price(yield_rate):
            discount = math.exp(-yield_rate*model.p.maturity)
            return model.c*(-math.expm1(-yield_rate*model.p.maturity))/yield_rate+model.principal_unit*discount
        yield_rate = brentq(lambda y: yield_price(y)-price, 1e-7, 10.)
        spread = 10000*(yield_rate-model.p.r)
        aggregate = quad(lambda t: float(model.debt(x, t)), 0., model.p.maturity,
                         epsabs=1e-10, epsrel=1e-11)[0]
        rows.append(dict(intensity=intensity, boundary=model.boundary,
                         new_debt_unit=price, aggregate_debt=aggregate,
                         yield_rate=yield_rate, spread_bps=spread,
                         paper_table_II_spread_bps=target,
                         spread_abs_error_bps=abs(spread-target),
                         passed=bool(abs(spread-target) < .5)))
    return dict(rows=rows, passed=all(row["passed"] for row in rows),
                note="Table I C and P are rounded to two decimals. Aggregate debt is nearly P; newly issued debt is not exactly par.")


def validate_parameter_derivatives():
    """Central finite differences versus independent roots at fixed V=100.

    The total equity derivative includes the induced movement of V_b. This
    does not test autodiff; it verifies that the analytic parameter map and
    independently reconstructed free-boundary map have consistent derivatives.
    """
    p = Parameters()
    rows = []
    for name in ["r", "delta", "sigma", "alpha", "tax", "liquidity", "maturity", "coupon", "principal"]:
        value = getattr(p, name)
        h = max(abs(value), .01)*1e-4

        def evaluate(offset, independent=False):
            model = HXModel(replace(p, **{name: value+offset}))
            b = boundary_from_quadrature(model) if independent else model.boundary
            x = math.log(100/b)
            equity = green_equity(model, x, b) if independent else float(model.equity(x))
            return np.array([b, equity])

        full = (evaluate(h)-evaluate(-h))/(2*h)
        half = (evaluate(h/2)-evaluate(-h/2))/h
        numeric = (evaluate(h/2, True)-evaluate(-h/2, True))/h
        scale = np.maximum(1., abs(numeric))
        error = float(np.max(abs(half-numeric)/scale))
        convergence = float(np.max(abs(full-half)/scale))
        rows.append(dict(parameter=name, step=h,
                         boundary_derivative=float(half[0]), equity_total_derivative=float(half[1]),
                         independent_boundary_derivative=float(numeric[0]),
                         independent_equity_total_derivative=float(numeric[1]),
                         scaled_reference_error=error, scaled_step_halving_change=convergence,
                         passed=bool(error < 2e-6 and convergence < 2e-6)))
    return dict(evaluation_asset_value=100., rows=rows, passed=all(row["passed"] for row in rows))


def validate_taylor_overlap():
    rows = []
    for name, override in [("baseline", {}), ("zero_liquidity", {"liquidity": 0.}),
                           ("short_maturity", {"maturity": 1e-4}),
                           ("low_volatility", {"sigma": .01}),
                           ("high_volatility", {"sigma": .8})]:
        model = HXModel(replace(Parameters(), **override))
        threshold = min(1e-4, 1e-3*model.s)
        x = threshold*np.array([.5, .99, 1., 1.01, 2.])
        e2, e3, e4 = model.boundary_taylor()
        taylor = x*x*(e2/2+x*(e3/6+x*e4/24))
        _, reference = precision_boundary_equity(model.p, x, digits=60)
        reference = np.asarray(reference)
        error = float(np.max(abs(taylor-reference)))
        public_error = float(np.max(abs(model.equity(x)-reference)))
        rows.append(dict(name=name, branch_threshold=threshold, log_distances=x.tolist(),
                         taylor_max_abs_error=error, public_max_abs_error=public_error,
                         passed=bool(error < 2e-8 and public_error < 2e-8)))
    return dict(rows=rows, passed=all(row["passed"] for row in rows))
