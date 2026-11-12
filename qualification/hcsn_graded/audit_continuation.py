"""All original posterior continuations after the ACTUAL graded/folded migration.

The fixed one-percent gate is unchanged. Spatial CTMC, initial/reset mapping
and upper-truncation errors are separated and cannot cancel into admission.
"""

import argparse
import hashlib
import inspect
import json
import math
from pathlib import Path
import time

import numpy as np

from qualification.hcsn_boundary_audit.spatial_generator import continuum_lower_hit
from qualification.hcsn_initial_law.migration import MigrationBasis
from qualification.hcsn_joint_dde.model import JointModel
from .model import GradedJointModel
from .spatial import GradedSpatialGenerator


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--original-finite-values",
        type=Path,
        default=Path(inspect.getfile(JointModel)).parent
        / "evidence/all-visits-attempt002/ALL_VISITS_128.npz",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu_started = time.perf_counter(), time.process_time()
    source_paths = [
        Path(__file__),
        Path(inspect.getfile(GradedJointModel)),
        Path(inspect.getfile(GradedSpatialGenerator)),
        Path(inspect.getfile(MigrationBasis)),
        Path(inspect.getfile(continuum_lower_hit)),
        Path(inspect.getfile(JointModel)),
    ]
    sources = {str(p): digest(p) for p in source_paths}
    inputs = {str(args.original_finite_values): digest(args.original_finite_values)}
    if (
        inputs[str(args.original_finite_values)]
        != "a0984f1a06fd47a803259e570f47aed07a48f0d44e44598a25a77a85782016c3"
    ):
        raise ValueError("original finite-continuum values changed")
    with np.load(args.original_finite_values, allow_pickle=False) as archive:
        old_rows = archive["rows"]
    lookup = {(int(row[0]), int(row[1])): (row[6], row[7]) for row in old_rows}
    if len(lookup) != 14336:
        raise ValueError("complete unique original references required")
    summary_path = args.original_audit / "SUMMARY.json"
    if (
        digest(summary_path)
        != "12fa561e6b5e6f710d1239d2a00bcf596da9d0060bf4691473ff337b7b5d0822"
    ):
        raise ValueError("original summary identity mismatch")
    inputs[str(summary_path)] = digest(summary_path)
    summary = json.loads(summary_path.read_text())
    records = []
    for arm_index, arm in enumerate(summary["arms"]):
        path = args.original_audit / arm["derived_trace_file"]
        if digest(path) != arm["derived_trace_sha256"]:
            raise ValueError("original trace identity mismatch")
        inputs[str(path)] = digest(path)
        lines = [json.loads(line) for line in path.read_text().splitlines()]
        if (
            lines[-1]["truncated"]
            or lines[-1]["retained_records"] != arm["expected_visits"]
        ):
            raise ValueError("original trace incomplete")
        records.extend((arm_index, row) for row in lines[1:-1])
    if len(records) != 14336:
        raise ValueError("all original positions required")
    cache, lifts, output, panels = {}, {}, {}, []
    for n in (256, 512):
        rows = []
        for arm_index, visit in records:
            p, physics, grid, config = (
                np.asarray(visit["posterior"][0]),
                visit["parameters"],
                visit["grid"],
                visit["operator"],
            )
            key = json.dumps(
                [n, physics, grid, config["active_reward"], config["hit_reward"]],
                sort_keys=True,
            )
            if key not in cache:
                spatial = GradedSpatialGenerator(
                    n, 8.0, physics["mu"], physics["sigma"]
                )
                reset = math.log(physics["absolute_reset"]) - physics["log_boundary"]
                model = GradedJointModel(
                    spatial,
                    reset,
                    grid["refractory"],
                    physics["discount"],
                    config["active_reward"],
                    config["hit_reward"],
                )
                lift_key = json.dumps([n, grid], sort_keys=True)
                if lift_key not in lifts:
                    basis = MigrationBasis(
                        grid["endpoint"],
                        grid["active_cells"],
                        grid["tail_rate"],
                        grid["refractory"],
                        grid["phase_cells"],
                        8.0,
                        n,
                        actual_nodes=tuple(spatial.nodes),
                    )
                    lifted = basis.lift()
                    lifts[lift_key] = np.asarray(lifted.weights, dtype=np.float64)
                weights = lifts[lift_key]
                candidate_nodes, candidate_reset = model.perpetual()
                continuum_phi = continuum_lower_hit(
                    spatial.nodes,
                    8.0,
                    physics["mu"],
                    physics["sigma"],
                    physics["discount"],
                )
                _, _, _, reset_weights = model.ingredients()
                reset_phi = float(reset_weights @ continuum_phi[1:-1])
                q, a, h, eta = (
                    physics["discount"],
                    config["active_reward"],
                    config["hit_reward"],
                    math.exp(-physics["discount"] * grid["refractory"]),
                )
                base = a / q
                continuum_reset = (base * (1 - reset_phi) + h * reset_phi) / (
                    1 - eta * reset_phi
                )
                continuum_nodes = base + continuum_phi * (
                    h + eta * continuum_reset - base
                )
                phase_edges = np.linspace(
                    0, grid["refractory"], grid["phase_cells"] + 1
                )
                phase_means = np.asarray(
                    [
                        math.exp(-q * lo)
                        * -math.expm1(-q * (hi - lo))
                        / (q * (hi - lo))
                        for lo, hi in zip(phase_edges[:-1], phase_edges[1:])
                    ]
                )
                cache[key] = (
                    np.r_[weights @ candidate_nodes, phase_means * candidate_reset],
                    np.r_[weights @ continuum_nodes, phase_means * continuum_reset],
                )
            candidate_basis, migrated_continuum_basis = cache[key]
            reference, original_finite = lookup[(arm_index, visit["index"])]
            candidate, mapped_continuum = (
                float(p @ candidate_basis),
                float(p @ migrated_continuum_basis),
            )
            scale = max(1.0, abs(reference))
            spatial_error = candidate - mapped_continuum
            migration_reset_error = mapped_continuum - original_finite
            truncation_error = original_finite - reference
            total = abs(candidate - reference) / scale
            conservative = (
                abs(spatial_error) + abs(migration_reset_error) + abs(truncation_error)
            ) / scale
            rows.append(
                [
                    arm_index,
                    visit["index"],
                    candidate,
                    mapped_continuum,
                    original_finite,
                    reference,
                    total,
                    conservative,
                    spatial_error,
                    migration_reset_error,
                    truncation_error,
                ]
            )
        values = np.asarray(rows)
        path = args.output / f"ALL_VISITS_n{n}.npz"
        np.savez_compressed(
            path,
            rows=values,
            columns=np.asarray(
                [
                    "arm_index",
                    "visit_index",
                    "candidate_after_actual_migration",
                    "finite_continuum_after_same_initial_reset_migration",
                    "finite_continuum_original_law",
                    "original_80digit_reference",
                    "scaled_error",
                    "non_cancelling_scaled_error",
                    "spatial_ctmc_error",
                    "initial_reset_migration_error",
                    "upper_truncation_error",
                ]
            ),
        )
        output[path.name] = digest(path)
        panels.append(
            {
                "intervals": n,
                "positions": len(values),
                "maximum_scaled_error": float(max(values[:, 6])),
                "maximum_non_cancelling_scaled_error": float(max(values[:, 7])),
                "failures_at_original_0_01": int(sum(values[:, 6] > 0.01)),
                "non_cancelling_failures_at_0_01": int(sum(values[:, 7] > 0.01)),
            }
        )
    report = {
        "schema": "hcsn-graded-actual-migration-continuation-v1",
        "status": "HOLD_NO_GO",
        "original_threshold": 0.01,
        "threshold_unchanged": True,
        "panels": panels,
        "all_original_positions": 14336,
        "input_sha256": inputs,
        "inputs_unchanged": all(digest(p) == h for p, h in inputs.items()),
        "source_sha256_before": sources,
        "source_sha256_after": {str(p): digest(p) for p in source_paths},
        "output_sha256": output,
        "basis_solves": len(cache),
        "lift_geometry_count": len(lifts),
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu_started,
        "scope": "perpetual continuation of actual lower-fold/graded migration on exposed original posteriors; not filtering, finite rare-risk, gradients or new training",
    }
    if (
        not report["inputs_unchanged"]
        or report["source_sha256_before"] != report["source_sha256_after"]
    ):
        raise ValueError("source or original inputs changed")
    (args.output / "SUMMARY.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n"
    )
    print(json.dumps({"panels": panels, "wall_seconds": report["wall_seconds"]}))


if __name__ == "__main__":
    main()
