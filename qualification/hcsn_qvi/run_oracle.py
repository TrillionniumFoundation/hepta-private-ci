"""Execute and source-bind the finite control fixture in a new result file."""

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np

from .oracle import FiniteControl, Problem, cost_sensitivity


def run():
    problem = Problem()
    control = FiniteControl(problem)
    started = time.perf_counter()
    fixed, _ = control.evaluate(control.x <= 0.4)
    fixed_wall = time.perf_counter() - started
    learned, optimum, dp = (
        control.fit_soft_threshold(),
        control.policy_iteration(),
        control.value_iteration(),
    )
    wait, intervene = control.action_values(optimum["value"])
    cont_residual = (problem.discount + control.clock_rate) * (wait - optimum["value"])
    impulse_residual = intervene - optimum["value"]
    alternatives = [
        dict(
            group="fixed_threshold",
            threshold=0.4,
            objective=float(control.initial_weights @ fixed),
            policy_evaluations=1,
            wall_seconds=fixed_wall,
        ),
        dict(
            group="ordinary_learned_soft_threshold",
            threshold=learned["threshold"],
            temperature=learned["temperature"],
            objective=float(control.initial_weights @ learned["value"]),
            policy_evaluations=learned["policy_evaluations"],
            gradient_linear_solves=learned["gradient_linear_solves"],
            wall_seconds=learned["wall_seconds"],
        ),
        dict(
            group="finite_dp_qvi",
            boundary_bracket=control.boundary_bracket(optimum["policy"]),
            objective=float(control.initial_weights @ optimum["value"]),
            policy_evaluations=optimum["iterations"],
            wall_seconds=optimum["wall_seconds"],
        ),
    ]
    sweep, previous = [], None
    for cost in (0.1, 0.3, 0.6, 0.9, 1.2):
        case = FiniteControl(replace(problem, cost=cost))
        solved = case.policy_iteration()
        sweep.append(
            dict(
                cost=cost,
                boundary_bracket=case.boundary_bracket(solved["policy"]),
                changed_actions=None
                if previous is None
                else int(np.count_nonzero(previous != solved["policy"])),
            )
        )
        previous = solved["policy"]
    refinement = []
    for nodes in (21, 41, 81):
        case = FiniteControl(replace(problem, nodes=nodes))
        solved = case.policy_iteration()
        refinement.append(
            dict(
                nodes=nodes,
                objective=float(case.initial_weights @ solved["value"]),
                boundary_bracket=case.boundary_bracket(solved["policy"]),
                condition_inf=solved["condition_inf"],
                wall_seconds=solved["wall_seconds"],
            )
        )
    sensitivity = cost_sensitivity(problem)
    difference = float(np.max(np.abs(optimum["value"] - dp["value"])))
    passed = (
        optimum["bellman_residual"] <= 1e-10
        and difference <= 2e-9
        and sensitivity["active_set_unchanged"]
        and sensitivity["maximum_absolute_difference"] <= 1e-7
    )
    return dict(
        problem=asdict(problem),
        groups=alternatives,
        learned_threshold_history=learned["history"],
        active_set_sweep=sweep,
        refinement=refinement,
        implicit_cost_gradient=sensitivity,
        bellman_residual=optimum["bellman_residual"],
        maximum_generator_residual_on_continue=float(
            np.max(np.abs(cont_residual[~optimum["policy"]]))
        ),
        maximum_value_matching_residual_on_intervene=float(
            np.max(np.abs(impulse_residual[optimum["policy"]]))
        ),
        maximum_generator_inequality_violation=float(max(0, cont_residual.max())),
        maximum_intervention_inequality_violation=float(max(0, impulse_residual.max())),
        condition_inf=optimum["condition_inf"],
        policy_iteration_active_counts=optimum["active_history"],
        independent_dp=dict(
            iterations=dp["iterations"],
            wall_seconds=dp["wall_seconds"],
            value_error_bound=dp["value_error_bound"],
            difference_from_policy_iteration=difference,
        ),
        finite_fixture_passed=passed,
        neural_task_benefit_established=False,
        continuum_free_boundary_certified=False,
        physical_energy_joules=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("preserve existing evidence; use a new output path")
    root = Path(__file__).parent
    sources = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.suffix in (".py", ".md")
    }
    started = time.perf_counter()
    report = dict(
        schema="hcsn-finite-qvi-oracle-v1",
        started_utc=datetime.now(timezone.utc).isoformat(),
        python=platform.python_version(),
        numpy=np.__version__,
        source_sha256=sources,
        scope="Finite bounded control fixture only; no neural training or continuum optimum credit",
    )
    report.update(run())
    report["total_wall_seconds"] = time.perf_counter() - started
    after = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.suffix in (".py", ".md")
    }
    report["source_unchanged"] = after == sources
    report["finite_fixture_passed"] = (
        report["finite_fixture_passed"] and report["source_unchanged"]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "finite_fixture_passed",
                    "bellman_residual",
                    "total_wall_seconds",
                )
            }
        )
    )
    return 0 if report["finite_fixture_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
