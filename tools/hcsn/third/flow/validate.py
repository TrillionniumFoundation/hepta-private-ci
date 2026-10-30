"""Small independent continuous-process audit; does not run content training."""

import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import scipy

from continuous_reference import GRADIENT_ORDER, renewal_statistics
from finite_grid_reference import finite_grid_statistics


ROOT = Path(__file__).resolve().parent
SOURCE_COMMIT = "e0c7da64463627ebc1a383bd267af7dc96753dc1"
BASE = dict(initial=0.7, reset=0.7, nu=-0.7, sigma=0.5,
            refractory_mean=0.4, duration=6.0)


def derivative_check(parameters, law):
    result = renewal_statistics(**parameters, law=law)
    expected = np.array(result["count_gradient"])
    finite = []
    for name in GRADIENT_ORDER:
        epsilon = 2e-5 * max(1.0, abs(parameters[name]))
        plus, minus = dict(parameters), dict(parameters)
        plus[name] += epsilon
        minus[name] -= epsilon
        high = renewal_statistics(**plus, law=law)["expected_events"]
        low = renewal_statistics(**minus, law=law)["expected_events"]
        finite.append((high - low) / (2 * epsilon))
    finite = np.array(finite)
    normalized = abs(expected - finite) / np.maximum(1.0, abs(expected))
    return dict(parameters=parameters, law=law, derivative_order=GRADIENT_ORDER,
                analytic_integral_gradient=expected.tolist(),
                central_difference_gradient=finite.tolist(),
                maximum_normalized_error=float(normalized.max()),
                passed=bool(normalized.max() < 2e-7))


def main():
    started = time.perf_counter()
    continuous = renewal_statistics(**BASE)
    spatial = []
    for cells in (8, 16, 32, 64, 128, 256, 512):
        row = finite_grid_statistics(**BASE, cells=cells, upper_wall=2.8)
        row["signed_event_error"] = row["expected_events"] - continuous["expected_events"]
        row["relative_event_error"] = row["signed_event_error"] / continuous["expected_events"]
        row["refractory_error"] = row["refractory_mass"] - continuous["refractory_mass"]
        spatial.append(row)
    walls = []
    for wall in (1.0, 1.5, 2.8, 4.0):
        row = finite_grid_statistics(**BASE, cells=round(wall / 0.025), upper_wall=wall)
        row["signed_event_error"] = row["expected_events"] - continuous["expected_events"]
        walls.append(row)
    for row in walls:
        row["event_difference_from_wall_4"] = row["expected_events"] - walls[-1]["expected_events"]
    counter_parameters = dict(initial=0.15, reset=0.15, nu=-1.0, sigma=0.4,
                              refractory_mean=0.5, duration=0.45)
    counterexample = {law: renewal_statistics(**counter_parameters, law=law, terms=48)
                      for law in ("deterministic", "erlang")}
    gradients = [derivative_check(BASE, law) for law in ("deterministic", "erlang")]
    gradients.append(derivative_check(dict(BASE, nu=0.3, sigma=0.7, duration=2.0), "erlang"))
    # Existing CTMC mass conservation is checked only on new refinement cases.
    numerical_cases = spatial + walls
    checks = dict(
        new_finite_grid_cases_conserve_mass=all(row["mass_error"] < 2e-10 for row in numerical_cases),
        new_finite_grid_cases_nonnegative=all(row["minimum_probability"] >= -1e-13 for row in numerical_cases),
        continuous_inventory_valid=0 <= continuous["refractory_mass"] <= 1,
        renewal_tail_bounded=continuous["count_tail_bound"] < 1e-12,
        fine_grid_closer_than_eight_cells=abs(spatial[-1]["signed_event_error"]) < abs(spatial[0]["signed_event_error"]),
        local_count_gradients=all(row["passed"] for row in gradients),
        deterministic_second_emission_impossible=counterexample["deterministic"]["event_cdfs"][1] == 0,
        erlang_second_emission_possible=counterexample["erlang"]["event_cdfs"][1] > 0.1)
    result = dict(
        schema="hcsn-continuous-renewal-reference-v1",
        source_provenance=dict(repository="TrillionniumFoundation/hepta-private-ci",
            pull_request=4255, commit=SOURCE_COMMIT,
            path="experiments/hcsn_distributional_v2/distribution_kernel.py",
            sha256="07195028877b4eb24f1bb1b53f1337019daf7bdabbdecbcd059f89079ba23de6",
            method="Read source and independently assembled its documented rates; did not execute the PR kernel"),
        baseline_parameters=BASE, continuous=continuous, spatial_refinement=spatial,
        wall_refinement=walls, refractory_counterexample=dict(parameters=counter_parameters, **counterexample),
        count_gradient_checks=gradients, checks=checks, passed=all(checks.values()),
        limits=["No model training, learned boundary, time-varying drift, coupling or production measurement",
                "Fixed finite generator is evaluated independently; the PR's 8.1 uniformization profile is not run on refined grids",
                "Quadrature error is a numerical estimate; only the omitted renewal count tail has the stated analytic bound",
                "Spatial error is not monotone because interpolation, upwind and boundary errors can cancel",
                "Count derivatives are of a fixed finite renewal sum, not an arbitrary recurrent-network gradient"],
        environment=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__),
        elapsed_seconds=time.perf_counter() - started,
        source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob("*.py")})
    (ROOT / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(passed=result["passed"], checks=checks,
                         continuous_events=continuous["expected_events"],
                         eight_cell_error=spatial[0]["signed_event_error"],
                         last_grid_error=spatial[-1]["signed_event_error"],
                         max_gradient_error=max(row["maximum_normalized_error"] for row in gradients),
                         elapsed_seconds=result["elapsed_seconds"]), indent=2))
    if not result["passed"]:
        raise SystemExit("A declared mathematical check failed; raw results have been retained")


if __name__ == "__main__":
    main()
