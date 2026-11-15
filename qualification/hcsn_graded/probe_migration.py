"""Execute migrated old laws through the actual graded probability/content DDE."""

import argparse
import hashlib
import inspect
import json
import math
from pathlib import Path
import time

import numpy as np

from qualification.hcsn_initial_law.migration import MigrationBasis, migrate
from qualification.hcsn_joint_dde.model import JointModel
from .model import GradedJointModel
from .reference import original_basis
from .spatial import GradedSpatialGenerator


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-audit", type=Path, required=True)
    parser.add_argument("--original-experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu_started = time.perf_counter(), time.process_time()
    source_paths = [
        Path(__file__),
        Path(inspect.getfile(GradedJointModel)),
        Path(inspect.getfile(GradedSpatialGenerator)),
        Path(inspect.getfile(JointModel)),
        Path(inspect.getfile(MigrationBasis)),
        Path(inspect.getfile(original_basis)),
    ]
    source_before = {str(p): digest(p) for p in source_paths}
    summary_path = args.original_audit / "SUMMARY.json"
    if (
        digest(summary_path)
        != "12fa561e6b5e6f710d1239d2a00bcf596da9d0060bf4691473ff337b7b5d0822"
    ):
        raise ValueError("original summary identity mismatch")
    summary = json.loads(summary_path.read_text())
    selected, maximum, inputs = None, -1.0, {str(summary_path): digest(summary_path)}
    for arm in summary["arms"]:
        path = args.original_audit / arm["derived_trace_file"]
        if digest(path) != arm["derived_trace_sha256"]:
            raise ValueError("original sidecar changed")
        inputs[str(path)] = digest(path)
        for line in path.read_text().splitlines()[1:-1]:
            visit = json.loads(line)
            if visit["posterior"][0][0] > maximum:
                maximum = visit["posterior"][0][0]
                selected = arm, visit
    arm, visit = selected
    journal = (
        args.original_experiment / f"seed{arm['seed']}-{arm['arm']}" / "training.jsonl"
    )
    if digest(journal) != arm["original_training_trace_sha256"]:
        raise ValueError("original content journal identity mismatch")
    inputs[str(journal)] = digest(journal)
    row = json.loads(journal.read_text().splitlines()[visit["update_index"]])
    state = row["states"][visit["position"]]
    if state["probability"] != visit["posterior"]:
        raise ValueError("selected signed-content state is not the same posterior")
    parameters = visit["parameters"]
    reset = math.log(parameters["absolute_reset"]) - parameters["log_boundary"]
    cases = [
        (
            "original_maximum_first_cell_posterior",
            np.asarray(visit["posterior"][0]),
            np.asarray(state["content_mass"][0]),
        )
    ]
    for name, cell in (
        ("isolated_first_uniform", 0),
        ("isolated_first_phase", 17),
        ("isolated_exponential_tail", 16),
    ):
        p = np.zeros(25)
        p[cell] = 1.0
        cases.append((name, p, np.c_[2 * p, -3 * p]))
    gaps = np.asarray([0.001, 0.003, 0.02, 0.04, 0.08, 0.16])
    reports, arrays = [], {}
    for n in (256, 512):
        spatial = GradedSpatialGenerator(n, 8.0, parameters["mu"], parameters["sigma"])
        model = GradedJointModel(spatial, reset, 0.2, parameters["discount"])
        basis = MigrationBasis(
            4.8, 16, 1.0, 0.2, 8, 8.0, n, actual_nodes=tuple(spatial.nodes)
        )
        lift = basis.lift()
        for name, p, marked in cases:
            migrated = migrate(basis, p, marked, identity=f"{name}-{n}", lift=lift)
            active, content, phase = migrated.solve_inputs()
            trajectory = model.solve(
                gaps, active, content, phase, rtol=1e-12, atol=1e-14, max_step=0.002
            )
            measurements, references, quadrature_errors = [], [], []
            for gap, value in zip(gaps, trajectory["rows"]):
                actual = np.r_[
                    value["events"][0],
                    value["discounted_events"][0],
                    value["discounted_active_time"][0],
                ]
                reference = p @ original_basis(float(gap), reset, order=128)
                other = p @ original_basis(float(gap), reset, order=64)
                measurements.append(actual)
                references.append(reference)
                quadrature_errors.append(max(abs(reference - other)))
                arrays[f"{name}_n{n}_t{gap}_active"] = value["active"]
            actual, reference = np.asarray(measurements), np.asarray(references)
            arrays[f"{name}_n{n}_MHA"] = actual
            arrays[f"{name}_n{n}_continuum_MHA"] = reference
            reports.append(
                {
                    "case": name,
                    "intervals": n,
                    "migration": migrated.report,
                    "actual_M_H_A": actual.tolist(),
                    "continuum_M_H_A": reference.tolist(),
                    "maximum_absolute_error_M_H_A": np.max(
                        abs(actual - reference), axis=0
                    ).tolist(),
                    "maximum_relative_M_where_reference_at_least_1e-12": float(
                        max(
                            abs(actual[:, 0] - reference[:, 0])[
                                reference[:, 0] >= 1e-12
                            ]
                            / reference[:, 0][reference[:, 0] >= 1e-12]
                        )
                    )
                    if np.any(reference[:, 0] >= 1e-12)
                    else None,
                    "maximum_continuum_quadrature_disagreement": max(quadrature_errors),
                    "maximum_mass_residual": max(
                        abs(r["mass_residual"]) for r in trajectory["rows"]
                    ),
                    "maximum_content_residual": max(
                        max(abs(r["content_residual"])) for r in trajectory["rows"]
                    ),
                    "internal_steps": trajectory["internal_steps"],
                }
            )
    np.savez_compressed(args.output / "RAW_ROLLOUTS.npz", **arrays)
    result = {
        "schema": "hcsn-graded-migrated-actual-dde-v1",
        "status": "HOLD_NO_GO",
        "gaps": gaps.tolist(),
        "selection": {
            "arm": arm["arm"],
            "seed": arm["seed"],
            "visit_index": visit["index"],
            "update_index": visit["update_index"],
            "position": visit["position"],
            "first_cell_mass": maximum,
        },
        "cases": reports,
        "input_sha256": inputs,
        "inputs_unchanged": all(digest(p) == h for p, h in inputs.items()),
        "source_sha256_before": source_before,
        "source_sha256_after": {str(p): digest(p) for p in source_paths},
        "raw_array_sha256": digest(args.output / "RAW_ROLLOUTS.npz"),
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu_started,
        "limits": "Post-failure repair on exposed laws/gaps; no independent prospective gate, rare-tail relative accuracy, dt<.001, full filtered trajectory or training claim.",
    }
    if (
        not result["inputs_unchanged"]
        or result["source_sha256_before"] != result["source_sha256_after"]
    ):
        raise ValueError("source or original inputs changed during the actual rollout")
    (args.output / "SUMMARY.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "cases": len(reports),
                "actual_dde_executed": True,
                "wall_seconds": result["wall_seconds"],
            }
        )
    )


if __name__ == "__main__":
    main()
