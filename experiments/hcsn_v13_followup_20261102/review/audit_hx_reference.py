"""Independent bounded financial-reference audit, not neural acceptance."""

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import subprocess

from scipy.integrate import quad

from experiments.hcsn_hx_unified_v3 import hx


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(out):
    out.mkdir(parents=True, exist_ok=False)
    p = hx.HX()
    protocol = {
        "schema": "hcsn-v13-hx-reference-audit.v1",
        "primary_doi": "10.1111/j.1540-6261.2012.01721.x",
        "primary_url": "https://www.princeton.edu/~wxiong/papers/rollover.pdf",
        "primary_equations": ["1", "8", "9", "11", "12", "A7"],
        "reference_source": "experiments/hcsn_hx_unified_v3/hx.py",
        "reference_sha256": sha(hx.__file__),
        "auditor_sha256": sha(__file__),
        "git_head_at_start": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "fixed_financial_parameters": asdict(p),
        "interior_log_asset_over_boundary": [.02, .05, .1, .25, .5, 1., 2.],
        "hitting_probability_times": [.05, .5, 2.],
        "hitting_quadrature_atol": 1e-9,
        "equity_resolvent_atol": 2e-8,
        "interior_ode_absolute_tolerance": 2e-5,
        "smooth_pasting_log_derivative_absolute_tolerance": 3e-5,
        "scope": "Fixed financial-law value/probability and numerical reference admission; no trained neural or reset claim.",
    }
    (out / "PLAN.json").write_text(json.dumps(protocol, indent=2) + "\n")
    checks, failures = 0, []

    def check(ok, label):
        nonlocal checks
        checks += 1
        if not bool(ok):
            failures.append(label)

    b = hx.boundary(p)
    check(math.isfinite(b) and b > 0, "finite positive endogenous boundary")

    def hitting_integral(parameters, x, tau, discounted):
        sigma = parameters.volatility
        drift = parameters.rate - parameters.payout - .5 * sigma * sigma

        def density(t):
            if t <= 0:
                return 0.
            exponent = -(x + drift*t)**2 / (2*sigma*sigma*t)
            if exponent < -745:
                return 0.
            value = x * math.exp(exponent) / (sigma * math.sqrt(2*math.pi*t**3))
            return value * math.exp(-parameters.q*t) if discounted else value

        return quad(density, 0, tau, epsabs=1e-12, epsrel=1e-11, limit=200)

    rows, probability_rows = [], []
    for x in protocol["interior_log_asset_over_boundary"]:
        asset = b*math.exp(x)
        value = hx.equity_closed(p, asset, b)
        independent = hx.equity_resolvent(p, asset, b)
        check(value >= 0, "nonnegative interior equity")
        check(abs(value-independent) < protocol["equity_resolvent_atol"], "A7 versus independent Green resolvent")
        f = lambda z: hx.equity_closed(p, b*math.exp(z), b)
        step = 2e-4
        check(x > 2*step, "interior differentiation stencil stays above boundary")
        deriv = (f(x-2*step)-8*f(x-step)+8*f(x+step)-f(x+2*step))/(12*step)
        second = (-f(x-2*step)+16*f(x-step)-30*f(x)+16*f(x+step)-f(x+2*step))/(12*step*step)
        source = p.payout*asset-(1-p.tax_shield)*p.coupon+hx.bond_value(p, asset, p.maturity, b)-p.per_bond_principal
        residual = (p.rate-p.payout-.5*p.volatility**2)*deriv+.5*p.volatility**2*second-p.rate*value+source
        check(abs(residual) < protocol["interior_ode_absolute_tolerance"], "equity ODE in log coordinate")
        rows.append({"log_margin": x, "asset": asset, "equity_A7": value,
                     "equity_Green": independent, "absolute_difference": abs(value-independent),
                     "dE_dlog_asset_fd": deriv, "ode_residual_fd": residual})
        for tau in protocol["hitting_probability_times"]:
            f_value = hx.default_probability(p, asset, tau, b)
            g_value = hx.discounted_default_factor(p, asset, tau, b)
            f_integral, f_error = hitting_integral(p, x, tau, False)
            g_integral, g_error = hitting_integral(p, x, tau, True)
            check(0 <= g_value <= f_value <= 1, "probability and discount ordering")
            check(abs(f_value-f_integral) < protocol["hitting_quadrature_atol"], "F versus independent hitting density integral")
            check(abs(g_value-g_integral) < protocol["hitting_quadrature_atol"], "G versus independent discounted hitting density integral")
            probability_rows.append({"log_margin": x, "tau": tau, "F": f_value, "G": g_value,
                "F_integral": f_integral, "G_integral": g_integral,
                "quadrature_error_estimates_not_bounds": [f_error, g_error]})

    endpoint = {}
    for ratio in (.99, 1.):
        asset = b*ratio
        check(hx.equity_closed(p, asset, b) == 0, "default equity branch")
        check(hx.default_probability(p, asset, 0, b) == 1, "default event takes priority at time zero")
        check(hx.discounted_default_factor(p, asset, 0, b) == 1, "default discount factor at time zero")
        check(hx.bond_value(p, asset, 0, b) == p.recovery*b/p.maturity, "default recovery priority contract")
    asset = b*math.exp(.2)
    check(hx.default_probability(p, asset, 0, b) == 0, "surviving zero-time F")
    check(hx.discounted_default_factor(p, asset, 0, b) == 0, "surviving zero-time G")
    check(hx.bond_value(p, asset, 0, b) == p.per_bond_principal, "surviving zero-time principal")
    for step in (.01, .005, .001):
        values = [hx.equity_closed(p, b*math.exp(i*step), b) for i in range(5)]
        derivative = (-25*values[0]+48*values[1]-36*values[2]+16*values[3]-3*values[4])/(12*step)
        endpoint[str(step)] = {"one_sided_log_derivative": derivative, "positive_limit_equity": values[1]}
    check(abs(endpoint["0.001"]["one_sided_log_derivative"]) < protocol["smooth_pasting_log_derivative_absolute_tolerance"], "one-sided smooth pasting at endogenous boundary")
    check(endpoint["0.001"]["positive_limit_equity"] > 0, "interior value matching limit does not rely only on clamped endpoint")

    coalescent = []
    for hazard in (0., 1e-10, .015):
        parameters = replace(p, shock_intensity=1., sale_fraction=hazard)
        barrier = hx.boundary(parameters)
        for x in (.02, .5, 2.):
            value = hx.equity_closed(parameters, barrier*math.exp(x), barrier)
            independent = hx.equity_resolvent(parameters, barrier*math.exp(x), barrier)
            check(abs(value-independent) < protocol["equity_resolvent_atol"], "coalescent and ordinary financial equity")
            coalescent.append({"hazard": hazard, "log_margin": x, "equity": value,
                               "independent": independent, "abs_diff": abs(value-independent)})

    absolute_asset = b*math.exp(.2)
    moved = b*1.03
    absolute_effect = hx.default_probability(p, absolute_asset, p.maturity, moved)-hx.default_probability(p, absolute_asset, p.maturity, b)
    normalized_difference = hx.default_probability(p, moved*math.exp(.2), p.maturity, moved)-hx.default_probability(p, b*math.exp(.2), p.maturity, b)
    check(abs(absolute_effect) > .001, "moving boundary changes fixed-absolute-asset probability")
    check(abs(normalized_difference) < 1e-14, "normalized log-margin erases boundary from F")
    check(sha(hx.__file__) == protocol["reference_sha256"], "reference unchanged through collection")
    result = {"schema": protocol["schema"], "checks": checks, "passed": not failures,
        "failures": failures, "boundary": b, "interior": rows, "probabilities": probability_rows,
        "one_sided_boundary": endpoint, "coalescent": coalescent,
        "boundary_parameterization_counterexample": {"absolute_asset_probability_effect": absolute_effect,
            "co_moving_normalized_asset_probability_effect": normalized_difference},
        "scope": protocol["scope"], "global_regime_or_neural_acceptance": False}
    (out / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"checks": checks, "passed": result["passed"], "failures": failures,
                      "boundary": b, "largest_equity_reference_difference": max(r["absolute_difference"] for r in rows),
                      "largest_ode_residual": max(abs(r["ode_residual_fd"]) for r in rows)}))
    return result["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if main(args.out) else 1)
