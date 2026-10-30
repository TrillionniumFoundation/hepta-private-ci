"""Run the predeclared deterministic deadline cases without tuning any policy."""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback

import numpy as np
import scipy

from experiments.first_passage_operator.free_boundary import NaturalSpikeSpec
from .policy import evaluate_policy
from .qvi import solve_deadline


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def source_manifest():
    files = [p for p in PACKAGE.rglob("*") if p.is_file()
             and "results" not in p.relative_to(PACKAGE).parts
             and "__pycache__" not in p.parts]
    files.extend(ROOT / name for name in [
        "experiments/first_passage_cell/kernels.py",
        "experiments/first_passage_operator/free_boundary.py",
    ])
    return [{"path": p.relative_to(ROOT).as_posix(), "bytes": p.stat().st_size,
             "sha256": digest(p)} for p in sorted(files)]


def probes(protocol, spec):
    points = set(spec.spike_cost + offset for offset in protocol["probes"]["state_offsets_from_cost"])
    points.update([spec.reset, spec.spike_cost + 1 / spec.exponent + .1])
    result = [(h, x, 0.0) for h in protocol["probes"]["horizons"] for x in sorted(points)]
    result.extend((h, spec.reset, eta) for eta in protocol["probes"]["pending_refractory"]
                  for h in protocol["probes"]["horizons"])
    return result


def evaluate_probes(solution, points):
    return np.array([solution.value(h, x, eta) for h, x, eta in points])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("each numerical attempt requires a new empty output directory")
    output.mkdir(parents=True, exist_ok=True)
    protocol_path = PACKAGE / "PROTOCOL.json"
    protocol = json.loads(protocol_path.read_text())
    sources = source_manifest()
    write_json(output / "SOURCE_MANIFEST.json", sources)
    write_json(output / "PROTOCOL_COPY.json", protocol)
    started = time.monotonic()
    report = {
        "schema": "hepta.deadline-numerical-report.v1", "status": "running",
        "protocol_sha256": digest(protocol_path), "python": sys.version,
        "platform": platform.platform(), "numpy": np.__version__, "scipy": scipy.__version__,
        "thread_environment": {name: os.environ.get(name) for name in
                               ["OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"]},
        "cases": [], "gates": [],
        "scope": "Deterministic scalar numerical validation; no training, heldout reuse, network optimality or certified continuous optimality gap.",
    }

    def gate(name, value, limit):
        report["gates"].append({"name": name, "observed": float(value),
                                "limit": float(limit), "passed": bool(value <= limit)})

    try:
        for case in protocol["cases"]:
            spec = NaturalSpikeSpec(**{key: value for key, value in case.items()
                                       if key not in ["name", "horizon"]})
            points = probes(protocol, spec)
            previous_probes = None
            case_report = {"name": case["name"], "spec": asdict(spec), "levels": []}
            report["cases"].append(case_report)
            for index, grid in enumerate(protocol["refinements"]):
                solution = solve_deadline(spec, case["horizon"], **grid,
                                          tail_bound=protocol["lower_truncation_value_bound"])
                policy = evaluate_policy(spec, case["horizon"], solution.boundaries, **grid,
                                         tail_bound=protocol["lower_truncation_value_bound"],
                                         order=protocol["quadrature"]["primary_gauss_legendre_order"])
                lcp_probes = evaluate_probes(solution, points)
                policy_probes = evaluate_probes(policy, points)
                difference = float(np.max(np.abs(lcp_probes - policy_probes)))
                refinement = (None if previous_probes is None else
                              float(np.max(np.abs(lcp_probes - previous_probes))))
                row = {"level": index, "grid": grid, "lcp": solution.diagnostics,
                       "policy": policy.diagnostics, "lcp_vs_policy_probe_error": difference,
                       "lcp_probe_refinement_difference": refinement,
                       "boundary": np.column_stack([solution.time, solution.boundaries]).tolist(),
                       "probes": [{"horizon": h, "state": x, "pending": eta,
                                   "lcp": float(a), "policy": float(b)}
                                  for (h, x, eta), a, b in zip(points, lcp_probes, policy_probes)]}
                name = f"{case['name']}.level_{index}.json"
                write_json(output / name, row)
                case_report["levels"].append({"file": name, "grid": grid,
                                               "probe_error": difference,
                                               "refinement_difference": refinement})
                prefix = f"{case['name']}.level{index}"
                gate(prefix + ".lcp_residual", solution.diagnostics["complementarity_residual_max"],
                     protocol["gates"]["lcp_complementarity_residual_max"])
                gate(prefix + ".raw_killed_mass", policy.diagnostics["mass_defect_max"],
                     protocol["gates"]["killed_mass_defect_max"])
                gate(prefix + ".negative_weights", policy.diagnostics["negative_weight_mass_max"], 0.0)
                gate(prefix + ".lower_truncation", solution.diagnostics["lower_truncation_value_bound"],
                     protocol["lower_truncation_value_bound"] * (1 + 1e-12))
                gate(prefix + ".single_stop_upper_bound", max(solution.boundaries)
                     - solution.diagnostics["single_stop_boundary"], grid["dx"] + 1e-12)
                gate(prefix + ".expiry_boundary", abs(solution.boundaries[1]
                     - solution.diagnostics["boundary_positive_time_limit"]),
                     3 * spec.sigma * np.sqrt(grid["dt"]) + 2 * grid["dx"])
                previous_probes = lcp_probes
                write_json(output / "RESULTS.json", report)
                print(json.dumps({"case": case["name"], "level": index,
                                  "policy_difference": difference, "mass_defect": policy.diagnostics["mass_defect_max"]}), flush=True)
            gate(case["name"] + ".finest_lcp_vs_policy", difference,
                 protocol["gates"]["finest_lcp_vs_policy_probe_error_max"])
            gate(case["name"] + ".last_lcp_refinement", refinement,
                 protocol["gates"]["last_lcp_refinement_probe_difference_max"])
            # Neither audit changes or reoptimizes the extracted threshold policy.
            audit = evaluate_policy(spec, case["horizon"], solution.boundaries, **grid,
                                    tail_bound=protocol["lower_truncation_value_bound"],
                                    order=protocol["quadrature"]["audit_order"])
            order_probes = evaluate_probes(audit, points)
            order_difference = float(np.max(np.abs(order_probes - policy_probes)))
            gate(case["name"] + ".quadrature_order", order_difference,
                 protocol["gates"]["quadrature_order_value_difference_max"])
            repeated = np.r_[solution.boundaries[0], np.repeat(solution.boundaries[1:], 2)]
            refined = evaluate_policy(spec, case["horizon"], repeated, dt=grid["dt"] / 2,
                                      dx=grid["dx"] / 2,
                                      tail_bound=protocol["lower_truncation_value_bound"],
                                      order=protocol["quadrature"]["audit_order"])
            refined_probes = evaluate_probes(refined, points)
            fixed_difference = float(np.max(np.abs(refined_probes - policy_probes)))
            gate(case["name"] + ".fixed_policy_refinement", fixed_difference,
                 protocol["gates"]["fixed_policy_refinement_probe_error_max"])
            gate(case["name"] + ".refined_mass", refined.diagnostics["mass_defect_max"],
                 protocol["gates"]["killed_mass_defect_max"])
            case_report["independent_audits"] = {
                "same_policy_quadrature_order_difference": order_difference,
                "fixed_policy_space_time_refinement_difference": fixed_difference,
                "order16_diagnostics": audit.diagnostics,
                "refined_diagnostics": refined.diagnostics,
                "refined_probe_values": refined_probes.tolist(),
                "no_policy_reoptimization": True,
            }
            write_json(output / "RESULTS.json", report)
        if source_manifest() != sources:
            raise RuntimeError("source changed while numerical validation was running")
        report["status"] = "passed predeclared numerical gates" if all(g["passed"] for g in report["gates"]) else "failed numerical gates"
        return 0 if report["status"].startswith("passed") else 1
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        traceback.print_exc()
        return 1
    finally:
        report["seconds"] = time.monotonic() - started
        write_json(output / "RESULTS.json", report)
        print(json.dumps({"status": report["status"], "seconds": report["seconds"]}), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
