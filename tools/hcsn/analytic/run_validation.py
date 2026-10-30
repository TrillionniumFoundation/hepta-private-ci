"""Execute independent full-model reproduction checks and write raw evidence.

Run from any directory: python analytic/run_validation.py
Dependencies: numpy, scipy, mpmath. No source PDF or network access required.
"""

from dataclasses import asdict, replace
from pathlib import Path
import hashlib
import json
import math
import platform
import sys
import time

import numpy as np
import scipy
import mpmath

if __package__:
    from .hx_model import HXModel, Parameters
    from .hx_precision import precision_boundary_equity
    from .hx_reference import (green_equity, boundary_from_quadrature,
                              boundary_and_equity_bvp, debt_pde)
    from .hx_validation_extras import (validate_calibration, validate_parameter_derivatives,
                                     validate_taylor_overlap)
else:
    from hx_model import HXModel, Parameters
    from hx_precision import precision_boundary_equity
    from hx_reference import (green_equity, boundary_from_quadrature,
                              boundary_and_equity_bvp, debt_pde)
    from hx_validation_extras import (validate_calibration, validate_parameter_derivatives,
                                     validate_taylor_overlap)


ROOT = Path(__file__).resolve().parent
SOURCE = "https://www.princeton.edu/~wxiong/papers/rollover.pdf"
AUTHOR_COPY = "https://zhiguohe.net/wp-content/uploads/2023/12/The-Journal-of-Finance-2012-HE-Rollover-Risk-and-Credit-Risk.pdf"


def five_point_first(function, x, h):
    return (function(x-2*h)-8*function(x-h)+8*function(x+h)-function(x+2*h))/(12*h)


def five_point_second(function, x, h):
    return (-function(x-2*h)+16*function(x-h)-30*function(x)+16*function(x+h)-function(x+2*h))/(12*h*h)


def parameter_cases():
    cases = [("baseline", {})]
    cases += [(f"liquidity_{v:g}", {"liquidity": v}) for v in [0., 1e-14, 1e-10, 1e-6, .1]]
    cases += [(f"maturity_{v:g}", {"maturity": v}) for v in [1e-8, 1e-6, 1e-4, .01, .1, 5., 20., 10000.]]
    cases += [(f"sigma_{v:g}", {"sigma": v}) for v in [.01, .03, .08, .8, 1.5]]
    cases += [(f"delta_{v:g}", {"delta": v}) for v in [1e-5, .2]]
    cases += [(f"recovery_{v:g}", {"alpha": v}) for v in [0., 1.]]
    cases += [(f"tax_{v:g}", {"tax": v}) for v in [0., .6]]
    cases += [("short_low_volatility", {"maturity": .01, "sigma": .03})]
    return [(name, replace(Parameters(), **overrides)) for name, overrides in cases]


def validate_values():
    xs = np.array([0., 1e-8, 1e-5, .001, .01, .1, .5, 1., 2.])
    rows = []
    for name, params in parameter_cases():
        model = HXModel(params)
        b_numeric = boundary_from_quadrature(model)
        exact = model.equity(xs)
        raw = model.equity_raw(xs)
        reference = np.array([green_equity(model, x, b_numeric) for x in xs])
        f, g = model.first_hit(xs, params.maturity)
        h = min(1e-6, 1e-4*model.s)
        ev = model.equity(h*np.arange(5))
        slope = (-25*ev[0]+48*ev[1]-36*ev[2]+16*ev[3]-3*ev[4])/(12*h)
        row = dict(name=name, parameters=asdict(params), boundary=model.boundary,
                   boundary_numerical=b_numeric,
                   boundary_abs_error=abs(model.boundary-b_numeric),
                   log_distances=xs.tolist(), equity=exact.tolist(),
                   equity_green=reference.tolist(),
                   stable_equity_max_abs_error=float(np.max(abs(exact-reference))),
                   raw_A7_max_abs_error=float(np.max(abs(raw-reference))),
                   raw_value_matching_abs_error=abs(float(model.equity_raw(0.))),
                   one_sided_smooth_pasting_abs_error=abs(float(slope)),
                   f_min=float(f.min()), f_max=float(f.max()),
                   g_min=float(g.min()), g_minus_f_max=float(np.max(g-f)),
                   high_precision_path=model.high_precision,
                   recovery_exceeds_face=params.alpha*model.boundary > params.principal+1e-10)
        row["passed"] = bool(row["boundary_abs_error"] < 2e-8
            and row["stable_equity_max_abs_error"] < 2e-7
            and row["one_sided_smooth_pasting_abs_error"] < 2e-5
            and np.all(np.diff(exact) >= -2e-8)
            and exact.min() >= -2e-8 and f.min() >= -2e-12
            and f.max() <= 1+2e-12 and g.min() >= -2e-12
            and np.max(g-f) <= 2e-12)
        rows.append(row)
        print(f"values {name}: {'PASS' if row['passed'] else 'FAIL'} "
              f"b_error={row['boundary_abs_error']:.3g} E_error={row['stable_equity_max_abs_error']:.3g}", flush=True)
    return rows


def validate_bvp():
    rows = []
    cases = [("baseline", {}), ("zero_liquidity", {"liquidity": 0.}),
             ("short_maturity", {"maturity": .01}),
             ("low_volatility", {"sigma": .03}),
             ("negative_log_drift", {"delta": .2})]
    points = np.array([.005, .02, .1, .4, 1.])
    for name, override in cases:
        model = HXModel(replace(Parameters(), **override))
        sol = boundary_and_equity_bvp(model)
        h = min(2e-4, .01*model.s)
        d1 = five_point_first(model.equity, points, h)
        d2 = five_point_second(model.equity, points, h)
        residual = .5*model.s2*d2+model.a*model.s2*d1-model.p.r*model.equity(points)+model.net_cashflow(points)
        row = dict(name=name, bvp_boundary=float(sol.p[0]),
                   boundary_abs_error=abs(float(sol.p[0])-model.boundary),
                   value_max_abs_error=float(np.max(abs(sol.sol(points)[0]-model.equity(points)))),
                   first_derivative_max_abs_error=float(np.max(abs(sol.sol(points)[1]-d1))),
                   ode_fd_residual_max_abs=float(np.max(abs(residual))),
                   finite_difference_step=h, collocation_nodes=int(len(sol.x)),
                   max_rms_residual=float(max(sol.rms_residuals)))
        row["passed"] = bool(row["boundary_abs_error"] < 2e-6
            and row["value_max_abs_error"] < 1e-5
            and row["first_derivative_max_abs_error"] < 2e-4
            and row["ode_fd_residual_max_abs"] < 2e-3)
        rows.append(row)
        print(f"BVP {name}: {'PASS' if row['passed'] else 'FAIL'} {row}", flush=True)
    return rows


def validate_debt_pde():
    rows = []
    for name, override in [("baseline", {}), ("zero_liquidity", {"liquidity": 0.}),
                           ("longer_maturity", {"maturity": 5.}),
                           ("high_volatility", {"sigma": .8})]:
        model = HXModel(replace(Parameters(), **override))
        errors = []
        for nodes in [600, 1200, 2400]:
            x, numerical = debt_pde(model, model.boundary, nodes, nodes//2)
            errors.append(float(np.max(abs(numerical-model.debt(x)))))
        ratios = [errors[i]/errors[i+1] for i in range(2)]
        row = dict(name=name, space_intervals=[600, 1200, 2400],
                   time_steps=[300, 600, 1200], max_abs_errors=errors,
                   observed_error_ratios=ratios,
                   observed_orders=[math.log2(v) for v in ratios])
        row["passed"] = bool(max(errors[-1:]) < 2e-4 and min(ratios) > 3.0)
        rows.append(row)
        print(f"PDE {name}: {'PASS' if row['passed'] else 'FAIL'} errors={errors}", flush=True)
    return rows


def validate_limits():
    p = Parameters()
    model = HXModel(p)
    # Exact removable singularity: compare implementation with its l'Hopital expression.
    expected_B = model.s*math.exp(-.5*(model.z*model.s)**2)/math.sqrt(2*math.pi)
    from scipy.special import ndtr
    expected_B -= model.z*model.s**2*ndtr(-model.z*model.s)
    actual_B = model.B_aux(-model.z)
    liquidity_grid = [0., 1e-14, 1e-12, 1e-10, 1e-8, 1e-6, 1e-4, .01]
    boundaries = [HXModel(replace(p, liquidity=val)).boundary for val in liquidity_grid]
    short_ms = [1e-2, 1e-4, 1e-6, 1e-8]
    short_bs = [HXModel(replace(p, maturity=val)).boundary for val in short_ms]
    short_limit = p.principal/p.alpha
    long_ms = [1., 10., 100., 1000., 10000.]
    long_bs = [HXModel(replace(p, maturity=val)).boundary for val in long_ms]
    long_limit = (1-p.tax)*p.coupon/p.r*model.gamma/(model.gamma+1)
    # Check high-precision literal formulas, including both poles and tiny maturity.
    precise = []
    for name, override in [("baseline", {}), ("zero_liquidity", {"liquidity": 0.}),
                           ("near_zero_liquidity", {"liquidity": 1e-10}),
                           ("tiny_maturity", {"maturity": 1e-8}),
                           ("low_sigma", {"sigma": .01}),
                           ("very_long_maturity", {"maturity": 10000.})]:
        parameters = replace(p, **override)
        current = HXModel(parameters)
        xx = np.array([0., 1e-8, 1e-5, .001, .1, 1.])
        b60, e60 = precision_boundary_equity(parameters, xx, digits=60)
        b90, e90 = precision_boundary_equity(parameters, xx, digits=90)
        row = dict(name=name, boundary=float(current.boundary), boundary_high_precision=b90,
                   boundary_abs_error=abs(current.boundary-b90),
                   public_equity_max_abs_error=float(np.max(abs(current.equity(xx)-np.array(e90)))),
                   oracle_60_90_max_abs_difference=float(np.max(abs(np.array(e60)-np.array(e90)))))
        row["passed"] = bool(row["boundary_abs_error"] < 2e-8
            and row["public_equity_max_abs_error"] < 2e-7
            and row["oracle_60_90_max_abs_difference"] < 1e-20)
        precise.append(row)
    out = dict(B_minus_z_limit_abs_error=abs(actual_B-expected_B),
               liquidity_grid=liquidity_grid, liquidity_boundaries=boundaries,
               short_maturities=short_ms, short_boundaries=short_bs,
               short_limit=short_limit, short_limit_last_abs_error=abs(short_bs[-1]-short_limit),
               long_maturities=long_ms, long_boundaries=long_bs,
               long_limit=long_limit, long_limit_last_abs_error=abs(long_bs[-1]-long_limit),
               high_precision_checks=precise)
    out["passed"] = bool(abs(actual_B-expected_B) < 1e-14
        and np.all(np.diff(boundaries) >= -2e-10)
        and np.all(np.diff(abs(np.array(short_bs)-short_limit)) < 0)
        and np.all(np.diff(abs(np.array(long_bs)-long_limit)) < 0)
        and all(row["passed"] for row in precise))
    print(f"limits: {'PASS' if out['passed'] else 'FAIL'}", flush=True)
    return out


def main():
    started = time.perf_counter()
    evidence = dict(schema="hepta.hcsn.hx_reproduction.v1", source=SOURCE,
                    verified_author_copy=AUTHOR_COPY,
                    equations=["8", "9", "12", "A5", "A7"],
                    baseline_parameters=asdict(Parameters()),
                    environment=dict(python=platform.python_version(), numpy=np.__version__,
                                     scipy=scipy.__version__, mpmath=mpmath.__version__),
                    methods=dict(float64="Stabilized A7/A5 expressions and explicit Eq.(12)",
                                 high_precision="Literal A5/A7 at 60 and 90 decimal digits",
                                 equity_reference="Absorbing Green quadrature and unknown-boundary collocation BVP",
                                 debt_reference="Independent Crank-Nicolson PDE with Rannacher startup"))
    evidence["parameter_checks"] = validate_values()
    evidence["bvp_checks"] = validate_bvp()
    evidence["debt_pde_checks"] = validate_debt_pde()
    evidence["limit_checks"] = validate_limits()
    evidence["calibration_checks"] = validate_calibration()
    evidence["parameter_derivative_checks"] = validate_parameter_derivatives()
    evidence["taylor_overlap_checks"] = validate_taylor_overlap()
    model = HXModel()
    x100 = math.log(100/model.boundary)
    evidence["baseline_at_V100"] = dict(boundary=model.boundary,
        debt_unit=float(model.debt(x100)), equity=float(model.equity(x100)),
        default_probability_one_year=float(model.first_hit(x100, 1.)[0]))
    evidence["all_passed"] = bool(all(row["passed"] for row in evidence["parameter_checks"])
        and all(row["passed"] for row in evidence["bvp_checks"])
        and all(row["passed"] for row in evidence["debt_pde_checks"])
        and evidence["limit_checks"]["passed"]
        and evidence["calibration_checks"]["passed"]
        and evidence["parameter_derivative_checks"]["passed"]
        and evidence["taylor_overlap_checks"]["passed"])
    evidence["elapsed_seconds"] = time.perf_counter()-started
    source_files = ["__init__.py", "hx_model.py", "hx_precision.py", "hx_reference.py", "hx_validation_extras.py", "run_validation.py"]
    evidence["source_sha256"] = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in source_files}
    evidence["inspected_pdf_sha256"] = "d5e424d7d2f9ef7be5ffdda208498c38b7095f9781515214dc7943f0b2cdc73c"
    (ROOT/"validation_results.json").write_text(json.dumps(evidence, indent=2)+"\n")
    print(json.dumps({"all_passed": evidence["all_passed"], "elapsed_seconds": evidence["elapsed_seconds"],
                      "baseline_at_V100": evidence["baseline_at_V100"]}, indent=2))
    if not evidence["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
