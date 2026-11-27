"""Compare continuous ODE free-boundary values with the existing finite DP."""

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import time

import mpmath as mp
import numpy as np

from .continuum import fixed_threshold, solve_boundary
from .oracle import FiniteControl, Problem


def high_precision(problem, cost=None):
    """Independent 80-digit equation solve using unscaled exponential bases."""
    p = problem
    mu, sigma, q, upper, reset, delay, initial = map(mp.mpf,
        (p.mu, p.sigma, p.discount, p.upper, p.reset, p.delay, p.initial))
    cost = mp.mpf(p.cost) if cost is None else mp.mpf(cost)
    root = mp.sqrt(mu**2 + 2 * q * sigma**2)
    rp, rm = (-mu + root) / sigma**2, (-mu - root) / sigma**2
    eta = mp.exp(-q * delay)

    def equations(a, c, boundary):
        def value(x):
            return x / q + mu / q**2 + a * mp.exp(rp * x) + c * mp.exp(rm * x)
        slope = lambda x: 1 / q + a * rp * mp.exp(rp * x) + c * rm * mp.exp(rm * x)
        return slope(upper), slope(boundary), value(boundary) + cost - eta * value(reset)

    # This solves all three equations simultaneously, independently of the
    # FP64 solver's derivative elimination and scalar bisection.
    a, c, boundary = mp.findroot(equations, (mp.mpf("-0.001"), mp.mpf(16), reset / 2),
                                 tol=mp.mpf("1e-65"), maxsteps=100)
    x = max(initial, boundary)
    value = x / q + mu / q**2 + a * mp.exp(rp * x) + c * mp.exp(rm * x)
    return boundary, value


def run():
    problem = Problem()
    solution = solve_boundary(problem)
    fixed = fixed_threshold(problem, 0.4)
    residuals, gradient = solution.residuals(), solution.cost_derivative()
    with mp.workdps(80):
        reference = high_precision(problem)
        step = mp.mpf("1e-25")
        plus = high_precision(problem, mp.mpf(problem.cost) + step)
        minus = high_precision(problem, mp.mpf(problem.cost) - step)
        reference_gradient = [(hi - lo) / (2 * step) for hi, lo in zip(plus, minus)]
        oracle = {
            "digits": 80, "boundary": str(reference[0]), "initial_value": str(reference[1]),
            "boundary_absolute_error": float(abs(mp.mpf(solution.boundary) - reference[0])),
            "initial_value_absolute_error": float(abs(mp.mpf(float(solution.value(problem.initial))) - reference[1])),
            "cost_difference_step": str(step),
            "cost_gradients": list(map(str, reference_gradient)),
            "cost_gradient_absolute_errors": [
                float(abs(mp.mpf(actual) - expected)) for actual, expected in
                zip((gradient["boundary"], gradient["initial_value"]), reference_gradient)],
        }
    finite = []
    for nodes in (21, 41, 81, 121):
        control = FiniteControl(replace(problem, nodes=nodes))
        solved = control.policy_iteration()
        reference_values = solution.value(control.x)
        finite.append({
            "nodes": nodes, "spacing": control.spacing,
            "initial_value": float(control.initial_weights @ solved["value"]),
            "initial_value_absolute_error": float(abs(control.initial_weights @ solved["value"]
                                                    - solution.value(problem.initial))),
            "maximum_grid_value_error": float(np.max(np.abs(solved["value"] - reference_values))),
            "boundary_bracket": control.boundary_bracket(solved["policy"]),
            "bellman_residual": solved["bellman_residual"],
            "condition_inf": solved["condition_inf"],
            "policy_evaluations": solved["iterations"],
            "wall_seconds": solved["wall_seconds"],
        })
    coarse = FiniteControl(replace(problem, nodes=21))
    dp = coarse.value_iteration()
    pi = coarse.policy_iteration()
    dp_difference = float(np.max(np.abs(dp["value"] - pi["value"])))
    limits = {"boundary_and_value_oracle_error": 2e-10, "cost_gradient_error": 2e-9,
              "equation_residual": 1e-10, "finest_grid_value_error": 0.05,
              "independent_dp_difference": 2e-9}
    equation_keys = ("value_matching", "smooth_pasting", "upper_reflection",
                     "maximum_continuation_ode_residual")
    refinement_decreases = all(a["maximum_grid_value_error"] > b["maximum_grid_value_error"]
                              for a, b in zip(finite[:-1], finite[1:]))
    passed = (
        max(oracle["boundary_absolute_error"], oracle["initial_value_absolute_error"]) <= 2e-10
        and max(oracle["cost_gradient_absolute_errors"]) <= 2e-9
        and max(abs(residuals[k]) for k in equation_keys) <= 1e-10
        and residuals["maximum_intervention_generator_residual"] <= 1e-10
        and residuals["minimum_sampled_continuation_slope"] >= -1e-10
        and residuals["minimum_sampled_continuation_gap"] >= -1e-10
        and finite[-1]["maximum_grid_value_error"] <= 0.05
        and refinement_decreases and dp_difference <= 2e-9
    )
    return {
        "problem": asdict(problem), "limits": limits, "fixture_passed": bool(passed),
        "boundary": solution.boundary, "fp64_root_bracket": solution.root_bracket,
        "root_bracket_is_certified_interval": False,
        "initial_value": float(solution.value(problem.initial)),
        "fixed_threshold": {"boundary": 0.4, "initial_value": float(fixed.value(problem.initial))},
        "residuals": residuals, "implicit_cost_gradient": gradient,
        "independent_high_precision": oracle, "finite_dp_refinement": finite,
        "grid_value_error_decreases": refinement_decreases,
        "independent_21_node_dp": {"difference": dp_difference, "iterations": dp["iterations"],
                                 "error_bound": dp["value_error_bound"]},
        "neural_task_benefit_established": False, "continuum_certificate": False,
        "physical_energy_joules": None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("retain previous evidence; choose a new output path")
    root = Path(__file__).resolve().parent
    paths = ("oracle.py", "continuum.py", "run_continuum.py")
    before = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}
    started = time.perf_counter()
    report = {"schema": "hcsn-continuum-boundary-comparison-v1",
              "started_utc": datetime.now(timezone.utc).isoformat(),
              "python": platform.python_version(), "numpy": np.__version__, "mpmath": mp.__version__,
              "source_sha256": before, "scope": "Independent bounded diffusion fixture; no neural fit or adoption."}
    report["fixture_passed"] = False
    try:
        report.update(run())
        report["status"] = "passed" if report["fixture_passed"] else "HOLD"
    except Exception as error:
        report.update(status="error", error_type=type(error).__name__, error_message=str(error))
    finally:
        report["wall_seconds"] = time.perf_counter() - started
        report["source_unchanged"] = before == {
            p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}
        report["fixture_passed"] = bool(report["fixture_passed"] and report["source_unchanged"])
        if not report["source_unchanged"]:
            report["status"] = "source_changed"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write(chr(10))
    # Read the complete published JSON, so trailing non-JSON data fails the CLI.
    with args.output.open(encoding="utf-8") as stream:
        readback = json.load(stream)
    print(json.dumps({"fixture_passed": readback["fixture_passed"],
                     "status": readback["status"], "wall_seconds": readback["wall_seconds"]}))
    return 0 if readback["fixture_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
