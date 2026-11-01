"""Continuous perpetual stopping benchmark; unrelated to a production HX cell.

The numerical solver sees the GBM generator and exercise payoff, not the exact
free boundary or continuation values. Policy iteration solves the obstacle LCP
on successively finer log-asset meshes. Truncation has fixed public endpoints.
"""

import argparse
import hashlib
import json
import platform
import time
from pathlib import Path

import numpy as np
import scipy
from scipy.linalg import solve_banded


PROTOCOL = dict(
    schema="hcsn-r17-perpetual-put-boundary-v1",
    cases=[dict(strike=100., discount=.05, drift=.03, volatility=.30),
           dict(strike=100., discount=.08, drift=.01, volatility=.22),
           dict(strike=100., discount=.04, drift=.04, volatility=.40)],
    intervals=[512, 1024, 2048, 4096], log_asset_domain=[-7., 9.],
    max_policy_iterations=10000, policy_tolerance=1e-11,
    gates=dict(finest_boundary_relative_error=.005,
               finest_value_relative_error=.0001,
               finest_smooth_pasting_error=.02,
               lcp_residual=1e-7),
    scope="Deterministic numerical development: GBM perpetual American put only; no scientific holdout, finite-horizon HX, regeneration, neural training, or production admission.")


def exact(strike, discount, drift, volatility):
    """Negative root and its value-matched smooth-pasted stopping boundary."""
    if strike <= 0 or discount <= 0 or volatility <= 0 or drift < 0:
        raise ValueError("Benchmark requires positive K/r/sigma and nonnegative drift")
    variance = volatility ** 2
    shifted = drift - variance / 2
    beta = (-shifted - np.sqrt(shifted ** 2 + 2 * variance * discount)) / variance
    boundary = strike * beta / (beta - 1)
    return float(beta), float(boundary)


def obstacle(case, intervals):
    """Solve min(V-g, (r-L)V)=0 with monotone central differences.

    Lower boundary is immediate exercise. Upper boundary is zero, independently
    of the closed form solution. No exact boundary/value enters policy iteration.
    """
    strike, discount, drift, volatility = (case[k] for k in
        ("strike", "discount", "drift", "volatility"))
    lower, upper = PROTOCOL["log_asset_domain"]
    x = np.linspace(lower, upper, intervals + 1)
    asset = strike * np.exp(x)
    payoff = np.maximum(strike - asset, 0.)
    dx = (upper - lower) / intervals
    diffusion, velocity = volatility ** 2 / 2, drift - volatility ** 2 / 2
    low = diffusion / dx ** 2 - velocity / (2 * dx)
    high = diffusion / dx ** 2 + velocity / (2 * dx)
    middle = discount + 2 * diffusion / dx ** 2
    if low <= 0 or high <= 0:
        raise ValueError("Central stencil is not monotone at this mesh")
    v = payoff.copy()
    v[-1] = 0.
    exercise = payoff[1:-1] > 0
    n = intervals - 1
    for iteration in range(PROTOCOL["max_policy_iterations"]):
        band = np.zeros((3, n))
        band[0, 1:] = -high
        band[1] = middle
        band[2, :-1] = -low
        rhs = np.zeros(n)
        rhs[0] += low * v[0]
        rhs[-1] += high * v[-1]
        band[1, exercise] = 1.
        indices = np.flatnonzero(exercise)
        band[0, indices[indices < n - 1] + 1] = 0.
        band[2, indices[indices > 0] - 1] = 0.
        rhs[exercise] = payoff[1:-1][exercise]
        candidate = solve_banded((1, 1), band, rhs, check_finite=False)
        continuation = middle * candidate - low * np.r_[v[0], candidate[:-1]] - high * np.r_[candidate[1:], v[-1]]
        contact = candidate - payoff[1:-1]
        next_exercise = contact <= continuation
        error = float(np.max(np.abs(candidate - v[1:-1])))
        v[1:-1] = candidate
        if np.array_equal(exercise, next_exercise) and error < PROTOCOL["policy_tolerance"]:
            break
        exercise = next_exercise
    else:
        raise RuntimeError("Obstacle policy iteration did not converge")
    residual = np.minimum(contact, continuation)
    active = np.flatnonzero(exercise & (payoff[1:-1] > 0))
    if not len(active):
        raise RuntimeError("No exercise boundary found")
    last = int(active[-1]) + 1
    beta, boundary = exact(**case)
    closed = np.where(asset <= boundary, strike - asset,
                      (strike - boundary) * (asset / boundary) ** beta)
    focused = (asset >= strike * .1) & (asset <= strike * 3)
    slope = (v[last + 2] - v[last + 1]) / (asset[last + 2] - asset[last + 1])
    return dict(intervals=intervals, mesh_log_spacing=dx, iterations=iteration + 1,
        grid_last_exercise_asset=float(asset[last]), grid_first_continuation_asset=float(asset[last + 1]),
        boundary_estimate=float((asset[last] + asset[last + 1]) / 2),
        exact_boundary=boundary,
        boundary_relative_error=float(abs((asset[last] + asset[last + 1]) / 2 - boundary) / strike),
        value_relative_error=float(np.max(np.abs(v[focused] - closed[focused])) / strike),
        continuation_slope=float(slope), smooth_pasting_error=float(abs(slope + 1)),
        lcp_residual=float(np.max(np.abs(residual))),
        obstacle_violation=float(max(0., -contact.min())),
        continuation_violation=float(max(0., -continuation.min())),
        monotone_stencil=True)


def run(output):
    """Freeze exact executed source/protocol locally before predetermined checks."""
    freeze_path = output.with_suffix(".freeze.json")
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with freeze_path.open("x") as handle:
        json.dump(dict(protocol=PROTOCOL, source_sha256=source_hash), handle, indent=2)
        handle.write("\n")
    started, wall = time.process_time(), time.perf_counter()
    rows, analytical = [], []
    for case in PROTOCOL["cases"]:
        beta, boundary = exact(**case)
        strike, discount, drift, volatility = (case[k] for k in
            ("strike", "discount", "drift", "volatility"))
        eps = boundary * 1e-5
        left_value = strike - boundary
        right_at_boundary = (strike - boundary) * (boundary / boundary) ** beta
        value_matching_error = abs(left_value - right_at_boundary)
        derivative = ((strike - boundary) * ((boundary + eps) / boundary) ** beta
                      - (strike - (boundary - eps))) / (2 * eps)
        # Substitute the analytic derivatives into the generator and obstacle.
        test_asset = boundary * np.array([1.001, 1.4, 3., 10.])
        values = (strike - boundary) * (test_asset / boundary) ** beta
        continuation_residual = (.5 * volatility ** 2 * beta * (beta - 1)
                                 + drift * beta - discount) * values
        exercise_residual = discount * strike - (discount - drift) * np.array([0., boundary])
        analytical.append(dict(case=case, beta=beta, boundary=boundary,
            value_matching_error=float(value_matching_error),
            smooth_pasting_error=float(abs(derivative + 1)),
            continuation_pde_residual=float(np.max(np.abs(continuation_residual))),
            exercise_residual_min=float(exercise_residual.min()),
            transversality_exponent_negative=beta < 0))
        for intervals in PROTOCOL["intervals"]:
            rows.append(dict(case=case, **obstacle(case, intervals)))
    finest = [r for r in rows if r["intervals"] == PROTOCOL["intervals"][-1]]
    gates = {key: all(r[key] < limit for r in finest)
             for key, limit in (("boundary_relative_error", PROTOCOL["gates"]["finest_boundary_relative_error"]),
                                ("value_relative_error", PROTOCOL["gates"]["finest_value_relative_error"]),
                                ("smooth_pasting_error", PROTOCOL["gates"]["finest_smooth_pasting_error"]),
                                ("lcp_residual", PROTOCOL["gates"]["lcp_residual"]))}
    gates["refinement_reduces_value_error"] = all(
        rows[j * 4 + 3]["value_relative_error"] < rows[j * 4]["value_relative_error"] for j in range(3))
    result = dict(schema=PROTOCOL["schema"], scope=PROTOCOL["scope"],
        protocol=PROTOCOL, source_sha256=source_hash, gates=gates,
        analytical=analytical, rows=rows, cpu_seconds=time.process_time() - started,
        wall_seconds=time.perf_counter() - wall,
        runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__))
    with output.open("x") as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps(dict(gates=gates, finest=finest, cpu_seconds=result["cpu_seconds"]), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    run(args.output)
