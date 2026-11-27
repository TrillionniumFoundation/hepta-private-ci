"""Independent numerical validation and adversarial checks for the scalar oracle.

Run: python oracle_tests.py --output results/oracle_validation.json
Torch checks run when torch is importable; their omission is recorded explicitly.
"""

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from scipy.integrate import quad
from scipy.optimize import minimize_scalar
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve
from scipy.stats import norm

from oracle import (OracleParams, PARAMETER_NAMES, continuation_gap,
                    discounted_hitting, first_passage_cdf,
                    first_passage_density, first_passage_survival,
                    finite_time_threshold_value,
                    intervention_value, kappa, renewal_reference,
                    solve_boundary, threshold_policy_value, value)


def finite_difference_qvi(params, lower=-10.0, upper=8.0, nodes=2401):
    """Independent monotone CTMC discretization and Howard policy iteration.

    This routine never calls the analytic boundary, characteristic root, or
    value. The left boundary is truncated to zero; the right boundary fires.
    Reset continuation uses linear interpolation. Upwind drift ensures a
    monotone generator; grid convergence is measured rather than assumed.
    """
    grid = np.linspace(lower, upper, nodes)
    dx = grid[1] - grid[0]
    up = 0.5 * params.sigma**2 / dx**2 + max(params.mu, 0) / dx
    down = 0.5 * params.sigma**2 / dx**2 + max(-params.mu, 0) / dx
    diagonal = params.rho + up + down
    reset_position = (params.r - lower) / dx
    reset_left = int(reset_position)
    weight = reset_position - reset_left
    if not (1 <= reset_left < nodes - 2):
        raise ValueError("Reset must be interior to independent finite-difference domain.")
    delta = math.exp(-params.rho * params.tau)
    fire = grid >= params.K + 1.0
    fire[0], fire[-1] = False, True
    for iteration in range(1, 201):
        matrix = lil_matrix((nodes, nodes))
        rhs = np.zeros(nodes)
        matrix[0, 0] = 1
        for i in range(1, nodes):
            if fire[i]:
                matrix[i, i] = 1
                matrix[i, reset_left] -= delta * (1 - weight)
                matrix[i, reset_left + 1] -= delta * weight
                rhs[i] = grid[i] - params.K
            else:
                matrix[i, i] = diagonal
                matrix[i, i + 1] = -up
                matrix[i, i - 1] = -down
        numerical = spsolve(matrix.tocsr(), rhs)
        reset_value = (1 - weight) * numerical[reset_left] + weight * numerical[reset_left + 1]
        immediate = grid - params.K + delta * reset_value
        continuation = np.zeros(nodes)
        continuation[1:-1] = (up * numerical[2:] + down * numerical[:-2]) / diagonal
        updated = immediate > continuation + 1e-13
        updated[0], updated[-1] = False, True
        if np.array_equal(updated, fire):
            break
        fire = updated
    else:
        raise AssertionError("Independent QVI policy iteration did not converge.")
    residual = np.minimum(numerical[1:-1] - immediate[1:-1],
                          numerical[1:-1] - continuation[1:-1])
    boundary = grid[np.flatnonzero(fire)[0]]
    return {"grid": grid, "value": numerical, "boundary": boundary,
            "dx": dx, "iterations": iteration,
            "bellman_residual_max": float(np.max(np.abs(residual)))}


def validation_report():
    started = time.perf_counter()
    checks = {}
    default = OracleParams()
    cases = [default, replace(default, mu=-0.35, sigma=0.5, tau=0.0),
             replace(default, mu=0.0, sigma=1.1, K=1.2, r=-0.5, tau=1.0),
             replace(default, mu=0.8, sigma=0.35, rho=0.6, tau=0.4)]
    root_records = []
    gradient_records = []
    for params in cases:
        sol = solve_boundary(params)
        grid = np.linspace(params.r - 5, sol.boundary + 5, 2001)
        j = value(grid, params, sol)
        obstacle_gap = continuation_gap(grid, params, sol)
        above = grid >= sol.boundary
        generator = params.mu - params.rho * (grid[above] - sol.boundary + 1 / sol.kappa)
        assert params.K < sol.boundary < params.K + 1 / sol.kappa
        assert abs(sol.residual) < 1e-12 and sol.root_jacobian > 0
        assert obstacle_gap.min() >= -1e-13 and generator.max() <= 1e-12
        assert np.all(j >= 0)
        eps = 1e-5
        left_slope = (value(sol.boundary, params) - value(sol.boundary - eps, params)) / eps
        right_slope = (value(sol.boundary + eps, params) - value(sol.boundary, params)) / eps
        assert abs(left_slope - right_slope) < 5e-5
        optimized = minimize_scalar(lambda b: -float(threshold_policy_value(params.r, b, params)),
                                    bounds=(params.K + 1e-6, params.K + 3 / sol.kappa), method="bounded")
        assert abs(optimized.x - sol.boundary) < 1e-4
        root_records.append({"parameters": asdict(params), "solution": asdict(sol),
                             "minimum_obstacle_gap": float(obstacle_gap.min()),
                             "maximum_action_generator": float(generator.max()),
                             "value_matching_error": float(abs(value(sol.boundary, params) - intervention_value(sol.boundary, params))),
                             "smooth_fit_slope_difference": float(abs(left_slope - right_slope)),
                             "independent_threshold_optimizer_error": abs(optimized.x - sol.boundary)})
        for name in PARAMETER_NAMES:
            h = 2e-5 * max(1, abs(getattr(params, name)))
            if name == "tau" and params.tau == 0:
                # Second-order one-sided derivative at the legal edge tau=0.
                base = sol.boundary
                estimate = (-3 * base + 4 * solve_boundary(replace(params, tau=h)).boundary
                            - solve_boundary(replace(params, tau=2 * h)).boundary) / (2 * h)
            else:
                estimate = (solve_boundary(replace(params, **{name: getattr(params, name) + h})).boundary
                            - solve_boundary(replace(params, **{name: getattr(params, name) - h})).boundary) / (2 * h)
            error = abs(estimate - sol.gradients[name]) / max(1, abs(estimate))
            assert error < 2e-7, (name, params, error)
            gradient_records.append({"parameter": name, "regime_mu": params.mu,
                                     "analytic": sol.gradients[name], "finite_difference": estimate,
                                     "scaled_absolute_error": error})
    checks["global_verification"] = root_records
    checks["joint_boundary_gradients"] = gradient_records

    independent = []
    for params in cases[:3]:
        sol = solve_boundary(params)
        comparisons = []
        for nodes in (1201, 2401, 4801):
            fd = finite_difference_qvi(params, nodes=nodes)
            target = value(fd["grid"], params)
            error = float(np.max(np.abs(fd["value"] - target)))
            interior = fd["grid"] >= params.r - 2
            interior_error = float(np.max(np.abs(fd["value"][interior] - target[interior])))
            comparisons.append({"nodes": nodes, "dx": fd["dx"], "max_value_error": error,
                                "interior_max_value_error": interior_error,
                                "left_boundary_truncation_error": float(target[0]),
                                "boundary_error": abs(fd["boundary"] - sol.boundary),
                                "iterations": fd["iterations"],
                                "bellman_residual_max": fd["bellman_residual_max"]})
        assert comparisons[-1]["max_value_error"] < 0.01
        assert comparisons[-1]["boundary_error"] <= 3 * comparisons[-1]["dx"]
        assert comparisons[-1]["interior_max_value_error"] < comparisons[0]["interior_max_value_error"]
        independent.append({"parameters": asdict(params), "grids": comparisons})
    checks["independent_monotone_qvi"] = independent

    integrals = []
    for params in cases:
        sol = solve_boundary(params)
        x, b = params.r, sol.boundary
        for horizon in (0.2, 1.0, 4.0):
            integral, err = quad(lambda t: float(first_passage_density(x, b, t, params.mu, params.sigma)),
                                 0, horizon, epsabs=1e-11, epsrel=1e-10)
            discounted_integral, _ = quad(lambda t: math.exp(-params.rho * t) * float(first_passage_density(x, b, t, params.mu, params.sigma)),
                                          0, horizon, epsabs=1e-11, epsrel=1e-10)
            f = float(first_passage_cdf(x, b, horizon, params.mu, params.sigma))
            s = float(first_passage_survival(x, b, horizon, params.mu, params.sigma))
            h = float(discounted_hitting(x, b, horizon, params.mu, params.sigma, params.rho))
            assert abs(integral - f) < 2e-10 and abs(discounted_integral - h) < 2e-10
            assert abs(f + s - 1) < 1e-12
            endpoint = norm.sf((b - x - params.mu * horizon) / (params.sigma * math.sqrt(horizon)))
            assert f >= endpoint
            integrals.append({"mu": params.mu, "horizon": horizon, "first_hit": f,
                              "endpoint_exceedance": endpoint, "cdf_integral_error": abs(integral - f),
                              "discounted_integral_error": abs(discounted_integral - h),
                              "probability_mass_error": abs(f + s - 1), "quadrature_error_estimate": err})
        infinite, _ = quad(lambda t: math.exp(-params.rho * t) * float(first_passage_density(x, b, t, params.mu, params.sigma)),
                           0, np.inf, epsabs=1e-11, epsrel=1e-10)
        assert abs(infinite - math.exp(-sol.kappa * (b - x))) < 1e-10
    checks["independent_first_passage_integrals"] = integrals

    # A killed Gaussian propagation check uses an integral, not the CDF formula.
    x, b, mu, sigma, elapsed, future = -0.2, 1.4, 0.25, 0.7, 0.8, 0.6
    distance = b - x
    reflection = math.exp(2 * mu * distance / sigma**2)
    scale = sigma * math.sqrt(elapsed)
    def killed_density(y):
        return (norm.pdf((y - x - mu * elapsed) / scale)
                - reflection * norm.pdf((y - (2 * b - x) - mu * elapsed) / scale)) / scale
    propagated, _ = quad(lambda y: killed_density(y) * float(first_passage_survival(y, b, future, mu, sigma)),
                         -np.inf, b, epsabs=1e-10)
    full = float(first_passage_survival(x, b, elapsed + future, mu, sigma))
    mass, _ = quad(killed_density, -np.inf, b, epsabs=1e-10)
    moment, _ = quad(lambda y: y * killed_density(y), -np.inf, b, epsabs=1e-10)
    image_mass = reflection * norm.cdf((-distance - mu * elapsed) / scale)
    moment_formula = (x + mu * elapsed) * mass - 2 * distance * image_mass
    assert abs(propagated - full) < 1e-10 and abs(moment - moment_formula) < 1e-10
    checks["killed_semigroup_and_first_moment"] = {"survival_semigroup_error": abs(propagated - full),
                                                  "killed_first_moment_error": abs(moment - moment_formula)}

    sol = solve_boundary(default)
    renewal_rows = []
    exact_short = finite_time_threshold_value(default.r, sol.boundary, default, horizon=4.0)
    exact_long = finite_time_threshold_value(default.r, sol.boundary, default, horizon=40.0)
    for dt in (0.1, 0.05, 0.025):
        reference = renewal_reference(default.r, sol.boundary, default, horizon=40.0, dt=dt)
        exact = float(value(default.r, default))
        error = abs(float(reference["value"][-1]) - exact)
        short_error = abs(float(reference["value"][round(4.0 / dt)]) - exact_short["value"])
        renewal_rows.append({"dt": dt, "horizon": 40.0, "renewal_value": float(reference["value"][-1]),
                             "single_fire_value": float(reference["single_fire_value"][-1]),
                             "infinite_horizon_exact": exact, "absolute_gap_to_infinite_horizon": error,
                             "short_horizon": 4.0, "short_horizon_exact_series": exact_short,
                             "short_horizon_quadrature_error": short_error,
                             "long_horizon_exact_series": exact_long,
                             "long_horizon_quadrature_error": abs(float(reference["value"][-1]) - exact_long["value"])})
    assert renewal_rows[-1]["absolute_gap_to_infinite_horizon"] < renewal_rows[0]["absolute_gap_to_infinite_horizon"]
    assert renewal_rows[-1]["absolute_gap_to_infinite_horizon"] < 0.003
    assert renewal_rows[-1]["short_horizon_quadrature_error"] < renewal_rows[0]["short_horizon_quadrature_error"]
    assert renewal_rows[-1]["short_horizon_quadrature_error"] < 0.001
    assert renewal_rows[-1]["renewal_value"] > 1.1 * renewal_rows[-1]["single_fire_value"]
    for p in cases:
        candidate = solve_boundary(p)
        finite = finite_time_threshold_value(p.r, candidate.boundary, p, horizon=40.0, atol=1e-13)
        assert finite["value"] <= float(value(p.r, p)) + finite["series_tail_upper_bound"]
        assert abs(finite["value"] - float(value(p.r, p))) < 1e-5
    checks["repeated_reset_refractory_renewal"] = renewal_rows

    degenerate = []
    increasing = replace(default, sigma=0, mu=0.5)
    numerical_small_noise = solve_boundary(replace(increasing, sigma=1e-5))
    exact_deterministic = solve_boundary(increasing)
    assert abs(numerical_small_noise.boundary - exact_deterministic.boundary) < 1e-8
    for mu in (-0.5, 0.0):
        p = replace(default, sigma=0, mu=mu)
        state = np.array([-1.0, 0.3, 1.0, 3.0])
        assert np.array_equal(value(state, p), np.maximum(state - p.K, 0))
        degenerate.append({"mu": mu, "sigma": 0, "regime": solve_boundary(p).regime,
                           "boundary": solve_boundary(p).boundary})
    near_singular = replace(default, r=default.K - 1e-8, tau=0)
    singular_sol = solve_boundary(near_singular)
    assert singular_sol.root_jacobian > 0 and singular_sol.gradients["K"] > 100
    no_regeneration = solve_boundary(replace(default, tau=1e4))
    assert abs(no_regeneration.boundary - (default.K + 1 / no_regeneration.kappa)) < 1e-12
    rejected = 0
    for p in (replace(default, r=default.K), replace(default, rho=0), replace(default, sigma=-1), replace(default, tau=-1)):
        try:
            solve_boundary(p)
        except ValueError:
            rejected += 1
    assert rejected == 4
    checks["degenerate_and_conditioning"] = {"deterministic_increasing_boundary_error": abs(numerical_small_noise.boundary - exact_deterministic.boundary),
                                             "deterministic_nonincreasing": degenerate,
                                             "near_chattering_root_jacobian": singular_sol.root_jacobian,
                                             "near_chattering_K_gradient": singular_sol.gradients["K"],
                                             "invalid_regimes_rejected": rejected}
    try:
        import torch
        from oracle_torch import analytic_value, first_passage_terms, free_boundary
    except ImportError:
        checks["torch_autograd"] = {"status": "not_run", "reason": "torch unavailable"}
    else:
        torch.set_num_threads(1)
        torch_records = []
        for params in cases:
            args = tuple(torch.tensor(getattr(params, name), dtype=torch.float64, requires_grad=True) for name in PARAMETER_NAMES)
            if params.tau == 0:
                # gradcheck perturbs both sides; use an interior refractory value.
                args = args[:-1] + (torch.tensor(0.1, dtype=torch.float64, requires_grad=True),)
                params = replace(params, tau=0.1)
            assert torch.autograd.gradcheck(free_boundary, args, eps=1e-6, atol=2e-6, rtol=2e-5)
            b = free_boundary(*args)
            actual = torch.autograd.grad(b, args)
            expected = solve_boundary(params)
            torch_records.append({"mu": params.mu, "boundary_error": abs(b.item() - expected.boundary),
                                  "maximum_analytic_gradient_error": max(abs(g.item() - expected.gradients[n]) for g, n in zip(actual, PARAMETER_NAMES))})
        base_args = tuple(torch.tensor(getattr(default, n), dtype=torch.float64, requires_grad=True) for n in PARAMETER_NAMES)
        for initial in (-0.2, 3.0):
            assert torch.autograd.gradcheck(lambda *a: analytic_value(torch.tensor(initial, dtype=torch.float64), *a),
                                            base_args, eps=1e-6, atol=2e-6, rtol=2e-5)
        for values in ((1.0, 0.2, 0.7, 0.5), (0.1, -1.0, 0.3, 0.02), (2.0, 2.0, 0.6, 3.0)):
            args = tuple(torch.tensor(v, dtype=torch.float64, requires_grad=True) for v in values)
            assert torch.autograd.gradcheck(first_passage_terms, args, eps=1e-6, atol=2e-6, rtol=2e-5)
        broadcast_args = tuple(torch.tensor(v, dtype=torch.float64, requires_grad=True) for v in
                               ([[-0.2], [0.3]], [[0.4, 0.8]], 0.4, 0.8, -0.2, 0.3))
        assert torch.autograd.gradcheck(free_boundary, broadcast_args, eps=1e-6, atol=2e-6, rtol=2e-5)
        checks["torch_autograd"] = {"status": "passed", "torch_version": torch.__version__,
                                     "boundary_cases": torch_records, "value_regions": 2,
                                     "first_passage_cases": 3, "broadcast_gradient_check": True,
                                     "higher_order_derivatives_certified": False}

    source_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in (Path(__file__), Path(__file__).with_name("oracle.py"), Path(__file__).with_name("oracle_torch.py"))}
    return {"schema": "hcsn.scalar-regenerative-oracle-validation.v1", "status": "passed",
            "scope": "stationary scalar infinite-horizon impulse-control oracle only",
            "finite_horizon_optimality_claimed": False, "neural_network_optimality_claimed": False,
            "checks": checks, "source_sha256": source_hashes,
            "runtime": {"python": platform.python_version(), "numpy": np.__version__,
                        "scipy": scipy.__version__, "wall_seconds": time.perf_counter() - started}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "results" / "oracle_validation.json")
    args = parser.parse_args()
    report = validation_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": report["status"], "output": str(args.output), "runtime": report["runtime"],
                      "torch": report["checks"]["torch_autograd"]["status"]}))
