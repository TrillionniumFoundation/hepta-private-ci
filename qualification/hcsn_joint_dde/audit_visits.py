"""Requalify continuation on all original, hash-bound retained posterior laws.

No training, filtering or historical optimizer replay is performed. This is a
new candidate's fixed-law continuation audit against the unchanged 1% gate.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from qualification.hcsn_boundary_audit.spatial_generator import KilledSpatialGenerator
from .basis import basis_values
from .model import JointModel


def checked(path, expected, identities):
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected:
        raise ValueError(f"input digest mismatch: {path}")
    identities[str(path.resolve())] = digest
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--summary-sha256", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    started, cpu_started = time.perf_counter(), time.process_time()
    source_paths = [
        Path(__file__),
        Path(__file__).with_name("model.py"),
        Path(__file__).with_name("basis.py"),
        Path(__file__).parents[1] / "hcsn_boundary_audit" / "spatial_generator.py",
        Path(__file__).parents[1] / "hcsn_boundary_audit" / "refractory_transport.py",
    ]
    sources_before = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths
    }
    args.output_dir.mkdir(parents=True, exist_ok=False)
    identities = {}
    summary = json.loads(
        checked(args.input_root / "SUMMARY.json", args.summary_sha256, identities)
    )
    roster = {
        (seed, arm)
        for seed in (11, 23, 37)
        for arm in ("c0_b0", "c0_b1", "c1_b0", "c1_b1")
    }
    if (
        len(summary["arms"]) != 12
        or {(a["seed"], a["arm"]) for a in summary["arms"]} != roster
    ):
        raise ValueError("complete original twelve-arm roster required")
    all_arrays, arm_reports, cache = [], [], {}
    maximum_reference_disagreement, total_rows = 0.0, 0
    for arm_index, arm in enumerate(summary["arms"]):
        raw = checked(
            args.input_root / arm["derived_trace_file"],
            arm["derived_trace_sha256"],
            identities,
        )
        lines = [json.loads(line) for line in raw.splitlines()]
        footer = lines[-1]
        if (
            footer["kind"] != "end"
            or footer["truncated"]
            or footer["dropped_records"] != 0
            or footer["retained_records"] != arm["expected_visits"]
        ):
            raise ValueError("original retained trace is incomplete")
        original = json.loads(
            checked(
                args.input_root / arm["raw_audit_file"],
                arm["raw_audit_sha256"],
                identities,
            )
        )
        visits, old_rows = lines[1:-1], original["visits"]
        if len(visits) != arm["expected_visits"] or len(old_rows) != len(visits):
            raise ValueError("original visit coverage changed")
        errors_by_grid = {n: [] for n in (128, 256, 512)}
        conservative_by_grid = {n: [] for n in errors_by_grid}
        for visit, old in zip(visits, old_rows):
            if (
                visit["index"] != old["index"]
                or visit["model_sha256"] != old["model_sha256"]
                or visit["update_index"] != old["update_index"]
            ):
                raise ValueError("old/new visit identity mismatch")
            grid, parameters, config = (
                visit["grid"],
                visit["parameters"],
                visit["operator"],
            )
            p = np.asarray(visit["posterior"], dtype=np.float64)
            if (
                p.shape != (1, grid["active_cells"] + 1 + grid["phase_cells"])
                or not np.isfinite(p).all()
                or p.min() < 0
                or abs(p.sum() - 1) > 5e-11
                or config["reset_enabled"] is not True
            ):
                raise ValueError("posterior law or regenerative configuration changed")
            reference = float(old["continuum_value"][0])
            for n in errors_by_grid:
                key = json.dumps(
                    [
                        grid,
                        parameters,
                        config["active_reward"],
                        config["hit_reward"],
                        n,
                    ],
                    sort_keys=True,
                )
                if key not in cache:
                    model = JointModel(
                        KilledSpatialGenerator(
                            n, 8.0, parameters["mu"], parameters["sigma"]
                        ),
                        math.log(parameters["absolute_reset"])
                        - parameters["log_boundary"],
                        grid["refractory"],
                        parameters["discount"],
                        config["active_reward"],
                        config["hit_reward"],
                    )
                    cache[key] = basis_values(
                        model,
                        original_endpoint=grid["endpoint"],
                        active_cells=grid["active_cells"],
                        phase_cells=grid["phase_cells"],
                        tail_rate=grid["tail_rate"],
                    )
                values = cache[key]
                candidate, finite, halfline = [
                    float(p[0] @ values[name])
                    for name in ("candidate", "finite_continuum", "halfline_continuum")
                ]
                reference_disagreement = abs(halfline - reference)
                maximum_reference_disagreement = max(
                    maximum_reference_disagreement, reference_disagreement
                )
                if reference_disagreement > 5e-12 * max(1, abs(reference)):
                    raise ArithmeticError(
                        "independent half-line formula disagrees with original 80-digit oracle"
                    )
                scale = max(1.0, abs(reference))
                error = abs(candidate - reference) / scale
                conservative = (
                    abs(candidate - finite) + abs(finite - reference)
                ) / scale
                errors_by_grid[n].append(error)
                conservative_by_grid[n].append(conservative)
                all_arrays.append(
                    (
                        arm_index,
                        visit["index"],
                        visit["update_index"],
                        visit["position"],
                        n,
                        candidate,
                        reference,
                        finite,
                        halfline,
                        error,
                        conservative,
                        old["maximum_scaled_value_error"],
                    )
                )
            total_rows += 1
        arm_reports.append(
            {
                "seed": arm["seed"],
                "arm": arm["arm"],
                "visits": len(visits),
                "training_rows": arm["training_rows"],
                "grids": {
                    str(n): {
                        "maximum_scaled_value_error": max(errors_by_grid[n]),
                        "maximum_non_cancelling_scaled_error": max(
                            conservative_by_grid[n]
                        ),
                        "failures_at_original_0_01": sum(
                            x > 0.01 for x in errors_by_grid[n]
                        ),
                        "non_cancelling_failures_at_0_01": sum(
                            x > 0.01 for x in conservative_by_grid[n]
                        ),
                    }
                    for n in errors_by_grid
                },
            }
        )
    if total_rows != 14336 or sum(a["training_rows"] for a in arm_reports) != 384:
        raise ValueError("expected all 14336 positions and 384 training rows")
    arrays = np.asarray(all_arrays, dtype=np.float64)
    columns = np.asarray(
        [
            "arm_index",
            "visit_index",
            "update_index",
            "position",
            "intervals",
            "candidate",
            "original_80digit_reference",
            "finite_continuum",
            "halfline_recheck",
            "scaled_error",
            "non_cancelling_scaled_error",
            "original_projected_scaled_error",
        ]
    )
    array_hashes = {}
    for intervals in (128, 256, 512):
        path = args.output_dir / f"ALL_VISITS_{intervals}.npz"
        np.savez_compressed(
            path, rows=arrays[arrays[:, 4] == intervals], columns=columns
        )
        array_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    result = {
        "schema": "hcsn-joint-dde-same-law-continuation-v1",
        "status": "HOLD_NO_GO",
        "fixed_law_continuation_gate": "passed"
        if all(
            a["grids"]["512"]["non_cancelling_failures_at_0_01"] == 0
            for a in arm_reports
        )
        else "failed",
        "original_scaled_value_error_limit": 0.01,
        "original_threshold_unchanged": True,
        "arms": arm_reports,
        "audited_positions": total_rows,
        "training_rows": 384,
        "maximum_recheck_vs_original_80digit_reference": maximum_reference_disagreement,
        "candidate_unique_basis_solves": len(cache),
        "candidate_endpoint": 8.0,
        "upper_semantics": "permanently active, nonreturning escape; explicit truncation",
        "input_sha256": identities,
        "inputs_unchanged": all(
            hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest
            for p, digest in identities.items()
        ),
        "array_sha256": array_hashes,
        "source_sha256_before": sources_before,
        "source_sha256_after": {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths
        },
        "limits": "Same retained reconstructed laws only. No posterior filtering, gradient, network training, task benefit or production qualification.",
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu_started,
    }
    if (
        not result["inputs_unchanged"]
        or result["source_sha256_before"] != result["source_sha256_after"]
    ):
        raise ArithmeticError("original evidence changed")
    (args.output_dir / "SUMMARY.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "audited_positions",
                    "candidate_unique_basis_solves",
                    "fixed_law_continuation_gate",
                    "wall_seconds",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
