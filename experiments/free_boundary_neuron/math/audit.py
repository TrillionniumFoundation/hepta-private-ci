"""Run registered numerical checks and preserve a machine-readable audit."""

import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np
import scipy
from scipy.integrate import quad
from scipy.optimize import minimize_scalar

from .finite_horizon import build_readout
from .hitting import fpt_density, hit_probability_and_gradient
from .moving import linear_boundary_readout, moving_boundary_reference
from .one_shot import one_shot_solution
from .renewal import renewal_objective, renewal_solution


DIRECTORY = Path(__file__).resolve().parent


def _scaled_error(measured, expected):
    return abs(measured - expected) / (1 + abs(expected))


def numerical_checks(protocol):
    metrics = dict.fromkeys(protocol["tolerances"], 0.0)
    cases = {"one_shot": [], "renewal": [], "moving": []}
    grid = protocol["one_shot_grid"]
    for mu, sigma, rate in itertools.product(grid["mu"], grid["sigma"], grid["rate"]):
        solution = one_shot_solution(mu, sigma, rate, grid["cost"])
        k, b = solution.roots.kappa, solution.boundary
        terms = (0.5 * sigma * sigma * k * k, mu * k, -rate)
        metrics["root_relative_residual"] = max(
            metrics["root_relative_residual"], abs(sum(terms)) / sum(map(abs, terms))
        )
        x = np.linspace(b - 8, b + 8, 1601)
        metrics["one_shot_obstacle_violation"] = max(
            metrics["one_shot_obstacle_violation"],
            float(np.max((x - grid["cost"]) - solution.value(x))),
        )
        metrics["one_shot_generator_violation"] = max(
            metrics["one_shot_generator_violation"],
            float(np.max(solution.generator_residual(x))),
        )
        opt = minimize_scalar(
            lambda barrier: -(barrier - grid["cost"]) * math.exp(-k * (barrier + 1)),
            bounds=(grid["cost"], b + 10 / k),
            method="bounded",
            options={"xatol": 1e-12},
        )
        metrics["one_shot_optimizer_boundary_error"] = max(
            metrics["one_shot_optimizer_boundary_error"], abs(opt.x - b)
        )
        cases["one_shot"].append(
            {
                "mu": mu,
                "sigma": sigma,
                "rate": rate,
                "boundary": b,
                "reference_boundary": float(opt.x),
            }
        )
    h = protocol["finite_difference_step"]
    for mu, sigma, gap, horizon, rate in (
        (0.7, 0.9, 1.3, 0.75, 0.4),
        (-0.6, 1.1, 1.7, 0.75, 0.2),
        (0.0, 0.5, 0.6, 0.75, 0.8),
    ):
        q, gradient = hit_probability_and_gradient(gap, horizon, mu, sigma, rate=rate)
        reference = quad(
            lambda t: math.exp(-rate * t) * float(fpt_density(t, gap, mu, sigma)),
            0,
            horizon,
            epsabs=1e-12,
            epsrel=1e-12,
        )[0]
        fd = (
            hit_probability_and_gradient(gap - h, horizon, mu, sigma, rate=rate)[0]
            - hit_probability_and_gradient(gap + h, horizon, mu, sigma, rate=rate)[0]
        ) / (2 * h)
        metrics["fpt_quadrature_error"] = max(
            metrics["fpt_quadrature_error"], abs(float(q) - reference)
        )
        metrics["fpt_gradient_scaled_error"] = max(
            metrics["fpt_gradient_scaled_error"],
            _scaled_error(float(fd), float(gradient)),
        )
    keys = ("mu", "sigma", "discount", "reset", "cost", "refractory")
    for parameters in protocol["renewal_cases"]:
        kwargs = dict(zip(keys, parameters))
        solution = renewal_solution(**kwargs)
        alternative = renewal_solution(**kwargs, method="brent")
        b = solution.boundary
        metrics["renewal_solver_boundary_error"] = max(
            metrics["renewal_solver_boundary_error"], abs(b - alternative.boundary)
        )
        opt = minimize_scalar(
            lambda barrier: -renewal_objective(barrier, *parameters),
            bounds=(max(kwargs["reset"], kwargs["cost"]) + 1e-8, b + 10),
            method="bounded",
            options={"xatol": 1e-12},
        )
        metrics["renewal_optimizer_boundary_error"] = max(
            metrics["renewal_optimizer_boundary_error"], abs(b - opt.x)
        )
        x = np.linspace(b - 8, b + 8, 1601)
        action = x - kwargs["cost"] + solution.delta * solution.reset_value
        metrics["renewal_obstacle_violation"] = max(
            metrics["renewal_obstacle_violation"],
            float(np.max(action - solution.value(x))),
        )
        metrics["renewal_generator_violation"] = max(
            metrics["renewal_generator_violation"],
            float(np.max(solution.generator_residual(x))),
        )
        for key in keys:
            if key == "refractory" and kwargs[key] == 0:
                continue  # Boundary parameter: no two-sided physical derivative.
            plus, minus = kwargs.copy(), kwargs.copy()
            plus[key] += h
            minus[key] -= h
            a, c = (
                renewal_solution(**plus, method="brent"),
                renewal_solution(**minus, method="brent"),
            )
            for label, measured, expected in (
                (
                    "renewal_boundary_gradient_scaled_error",
                    (a.boundary - c.boundary) / (2 * h),
                    solution.boundary_derivatives[key],
                ),
                (
                    "renewal_value_gradient_scaled_error",
                    (a.reset_value - c.reset_value) / (2 * h),
                    solution.value_derivatives[key],
                ),
            ):
                metrics[label] = max(metrics[label], _scaled_error(measured, expected))
        cases["renewal"].append(
            {
                "parameters": kwargs,
                "boundary": b,
                "value": solution.reset_value,
                "condition_index": solution.condition_index,
                "regime": solution.regime,
            }
        )
    exact = float(
        linear_boundary_readout(
            0.0, 0.8, 0.2, 1.2, 0.3, 0.7, killing=0.1, discount=0.2
        ).probability
    )
    curved_values = []
    for mesh in protocol["moving_meshes"]:
        linear = moving_boundary_reference(
            lambda t: 0.8 + 0.2 * t, 0.0, 1.2, 0.3, 0.7, killing=0.1, steps=mesh
        )
        curved = moving_boundary_reference(
            lambda t: 0.8 + 0.2 * t + 0.1 * t * t,
            0.0,
            1.2,
            0.3,
            0.7,
            killing=0.1,
            steps=mesh,
        )
        curved_values.append(curved.probability)
        cases["moving"].append(
            {
                "mesh": mesh,
                "linear": linear.probability,
                "linear_exact": exact,
                "linear_absolute_error": abs(linear.probability - exact),
                "curved": curved.probability,
            }
        )
        metrics["moving_negative_mass"] = max(
            metrics["moving_negative_mass"], linear.negative_mass, curved.negative_mass
        )
    metrics["moving_linear_last_error"] = cases["moving"][-1]["linear_absolute_error"]
    metrics["moving_curved_last_mesh_change"] = abs(
        curved_values[-1] - curved_values[-2]
    )
    near = renewal_solution(0.3, 0.8, 0.2, 0.0, 1e-12, 0.0)
    near_ref = renewal_solution(0.3, 0.8, 0.2, 0.0, 1e-12, 0.0, method="brent")
    metrics["near_degenerate_solver_relative_error"] = (
        abs(near.boundary - near_ref.boundary) / near_ref.boundary
    )
    readout = build_readout()
    transition = np.asarray(readout["transition"])
    value = np.asarray(readout["value"])
    continuation = np.asarray(readout["continuation"])
    metrics["owner_row_mass_error"] = float(
        np.max(
            abs(transition.sum(1) - math.exp(-readout["killing_rate"] * readout["dt"]))
        )
    )
    for n in (1, 7, 32):
        for i in (0, 17, 50, 83, 100):
            future = sum(
                float(p) * float(v) for p, v in zip(transition[i], value[n - 1])
            )
            expected = (
                -readout["running_cost"] * readout["dt"]
                + math.exp(-readout["rho"] * readout["dt"]) * future
            )
            metrics["owner_bellman_error"] = max(
                metrics["owner_bellman_error"], abs(expected - continuation[n, i])
            )
    checks = [
        {
            "name": key,
            "measured": float(measured),
            "tolerance": protocol["tolerances"][key],
            "passed": bool(
                np.isfinite(measured) and measured <= protocol["tolerances"][key]
            ),
        }
        for key, measured in metrics.items()
    ]
    monotone = all(
        cases["moving"][i + 1]["linear_absolute_error"]
        < cases["moving"][i]["linear_absolute_error"]
        for i in range(len(cases["moving"]) - 1)
    )
    checks.append(
        {"name": "moving_linear_error_decreases_on_each_refinement", "passed": monotone}
    )
    checks.append(
        {
            "name": "moving_curved_mesh_change_decreases",
            "passed": abs(curved_values[-1] - curved_values[-2])
            < abs(curved_values[-2] - curved_values[-3]),
        }
    )
    return {
        "checks": checks,
        "cases": cases,
        "near_degenerate_condition_index": near.condition_index,
    }, readout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DIRECTORY / "results")
    parser.add_argument("--source-seal", type=Path)
    args = parser.parse_args()
    started = datetime.now(timezone.utc)
    wall, cpu = time.perf_counter(), time.process_time()
    protocol = json.loads((DIRECTORY / "PROTOCOL.json").read_text())
    payload = {
        "schema": "hepta.free-boundary.math-audit.v1",
        "evidence_scope": "engineering_correctness_only",
        "phase": "sealed_numerical_audit" if args.source_seal else "unsealed_preflight",
        "started_at_utc": started.isoformat(),
        "command": [sys.executable, *sys.argv],
        "environment": {
            "python": sys.version,
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "platform": platform.platform(),
        },
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=DIRECTORY, text=True
        ).strip(),
        "source_hashes": {
            str(p.relative_to(DIRECTORY)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(DIRECTORY.rglob("*"))
            if p.is_file()
            and p.suffix in {".py", ".json"}
            and "results" not in p.relative_to(DIRECTORY).parts
        },
        "limitations": protocol["limitations"],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    try:
        if args.source_seal:
            from experiments.free_boundary_neuron.provenance import verify

            payload["source_verification"] = verify(args.source_seal)
        results, readout = numerical_checks(protocol)
        payload.update(results)
        encoded = (
            json.dumps(readout, separators=(",", ":"), allow_nan=False) + "\n"
        ).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        immutable = (
            args.output_dir / f"readout_{readout['profile_id']}_{digest[:12]}.json"
        )
        if not immutable.exists():
            immutable.write_bytes(encoded)
        (args.output_dir / "readout_affine_v1.json").write_bytes(encoded)
        payload["owner_readout"] = {
            "profile_id": readout["profile_id"],
            "sha256": digest,
            "immutable_file": immutable.name,
        }
        payload["status"] = (
            "passed" if all(c["passed"] for c in results["checks"]) else "failed"
        )
    except Exception as error:
        payload.update(status="invalid_execution", error=repr(error))
    payload["elapsed_wall_seconds"] = time.perf_counter() - wall
    payload["process_cpu_seconds"] = time.process_time() - cpu
    filename = "numerical_audit_" + started.strftime("%Y%m%dT%H%M%S%fZ") + ".json"
    destination = args.output_dir / filename
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    (args.output_dir / "latest_audit.json").write_text(
        json.dumps({"file": filename, "status": payload["status"]}) + "\n"
    )
    print(
        json.dumps(
            {
                "audit": str(destination),
                "status": payload["status"],
                "phase": payload["phase"],
            }
        )
    )
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
