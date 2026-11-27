"""Fixed-profile, all-retained-posterior right-tail continuation audit.

No training, optimizer, observation filter or DDE rollout is executed. Real
candidate perpetual() methods are called on each recorded physics/reset law.
The original 1% scaled continuation gate is unchanged; failure is retained.
"""

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import platform
import resource
import sys
import time

import mpmath
import numpy as np
import scipy

from qualification.hcsn_dense_reproduction.profile import NearDenseGenerator
from qualification.hcsn_graded.model import GradedJointModel
from qualification.hcsn_graded.spatial import GradedSpatialGenerator
from .migration1024 import MigrationBasis1024
from .cost_reference import values as reference_values


SUMMARY_SHA256 = "c60378ffc2a51f580a9b7cfd11a09cec5f53d9a9cc37c03b81605bedc54b8715"
PUBLISHED_SHA256 = "af6bb4f42bc4a89f1e9fa4a42f824544b230e8342b5585f88d9459ead4292af9"
PROFILES = (("v2exp512", 512, None, None), ("near8001024", 1024, 800, 0.5),
            ("near9601024", 1024, 960, 0.48))
LIMIT = 0.01


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"nonfinite JSON constant: {value}")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def checked(path, expected, identities):
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected:
        raise ValueError(f"original input digest mismatch: {path}")
    identities[str(path.resolve())] = digest
    return raw


def generator(profile, parameters):
    _, intervals, near, near_endpoint = profile
    args = (intervals, 8.0, parameters["mu"], parameters["sigma"])
    return (GradedSpatialGenerator(*args, stretch=6.0) if near is None else
            NearDenseGenerator(*args, stretch=6.0, near_intervals=near, near_endpoint=near_endpoint))


def summaries(array, columns):
    def column(name):
        return array[:, columns.index(name)]
    total = column("scaled_total_error")
    conservative = column("scaled_non_cancelling_error")
    return {
        "positions": len(array), "failures_at_unchanged_0_01": int(np.sum(total > LIMIT)),
        "non_cancelling_failures_at_unchanged_0_01": int(np.sum(conservative > LIMIT)),
        "maximum_scaled_total_error": float(total.max()),
        "median_scaled_total_error": float(np.median(total)),
        "maximum_scaled_non_cancelling_error": float(conservative.max()),
        "maximum_absolute_migration": float(np.max(np.abs(column("migration_signed")))),
        "maximum_absolute_discrete_operator_and_reset": float(np.max(np.abs(column("operator_reset_signed")))),
        "maximum_absolute_upper_nonreturning_truncation": float(np.max(np.abs(column("upper_truncation_signed")))),
        "maximum_absolute_tail_only_total_contribution": float(np.max(np.abs(column("tail_only_total_contribution")))),
        "maximum_absolute_whole_far_cells_total_contribution": float(np.max(np.abs(column("whole_far_cells_total_contribution")))),
        "maximum_decomposition_roundoff": float(column("decomposition_roundoff").max()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--candidate-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--published-reference", type=Path,
                        default=Path(__file__).parents[1] / "hcsn_graded/evidence/actual-migrated-continuation-attempt002/ALL_VISITS_n512.npz")
    parser.add_argument("--persisted-source-commit", required=True)
    args = parser.parse_args()
    started, cpu_started = time.perf_counter(), time.process_time()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=False)
    source_files = [Path(__file__), Path(__file__).with_name("cost_reference.py"),
                    Path(__file__).with_name("migration1024.py")]
    dependency_file = Path(__file__).with_name("COST_DEPENDENCIES.json")
    manifest = strict_json(dependency_file.read_bytes())
    sources_before = {}
    for relative, digest in manifest.items():
        path = args.candidate_root / relative
        checked(path, digest, sources_before)
        module = relative.removesuffix(".py").replace("/", ".")
        if module in sys.modules and Path(sys.modules[module].__file__).resolve() != path.resolve():
            raise ValueError("loaded candidate dependency differs from pinned root")
    for path in source_files + [dependency_file]:
        sources_before[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
    input_hashes = {}
    summary = strict_json(checked(args.input_root / "SUMMARY.json", SUMMARY_SHA256, input_hashes))
    published_raw = checked(args.published_reference, PUBLISHED_SHA256, input_hashes)
    with np.load(io.BytesIO(published_raw), allow_pickle=False) as archive:
        published = archive["rows"]
    if published.shape != (14336, 11) or not np.isfinite(published).all():
        raise ValueError("complete published 14336-reference corpus required")
    roster = {(seed, arm) for seed in (11, 23, 37) for arm in ("c0_b0", "c0_b1", "c1_b0", "c1_b1")}
    # Published arm_index inherits the original completion order: the pinned
    # fa258 audit_training_domain.py uses runs=summary["runs"], for run in
    # runs, then appends arms; 62f audit_continuation.py enumerates those arms.
    # Sorting the root SUMMARY would silently change the identity mapping.
    runs = summary["runs"]
    grid = summary["configuration"]["grid"]
    if (len(runs) != 12 or {(r["seed"], r["arm"]) for r in runs} != roster
            or summary["source_before"] != summary["source_after"]
            or grid != {"active_cells": 16, "endpoint": 4.8, "phase_cells": 8,
                        "refractory": 0.2, "tail_rate": 1.0, "quadrature_order": 16,
                        "initial_log_std": 0.08}):
        raise ValueError("original roster/source/grid identity changed")
    # Fixed geometry: no profile, stretch, near endpoint, gate or source
    # coefficient is tuned based on an observed continuation result.
    geometry_parameters = {"mu": -0.11999999999999998, "sigma": 0.35}
    lifts, geometry = {}, {}
    for profile in PROFILES:
        spatial = generator(profile, geometry_parameters)
        basis = MigrationBasis1024(grid["endpoint"], grid["active_cells"], grid["tail_rate"],
                                   grid["refractory"], grid["phase_cells"], 8.0,
                                   profile[1], actual_nodes=tuple(spatial.nodes))
        lift = basis.lift()
        matrix = np.asarray(lift.weights, dtype=float)
        if np.min(matrix) < 0 or np.any(matrix[:, 0] != 0):
            raise ArithmeticError("lift conversion violated sign/lower-atom condition")
        lifts[profile[0]] = (basis, lift, matrix)
        geometry[profile[0]] = {"intervals": profile[1], "near_intervals": profile[2],
            "endpoint": 8.0, "stretch": 6.0, "near_endpoint": profile[3],
            "node_hex": [float(x).hex() for x in spatial.nodes],
            "maximum_fp64_lift_row_sum_residual": float(np.max(np.abs(matrix.sum(1) - 1))),
            "lift_diagnostics": lift.diagnostics}
    columns = ["global_position", "arm_index", "training_step", "position", "physics_index", "reset",
               "halfline_original", "finite_original", "migrated_finite", "candidate_migrated",
               "migration_signed", "operator_reset_signed", "upper_truncation_signed",
               "scaled_total_error", "scaled_non_cancelling_error", "decomposition_roundoff",
               "source_tail_mass", "upper_initial_mass", "tail_only_total_contribution",
               "whole_far_cells_total_contribution", "published_halfline_reference",
               "new_vs_published_reference_delta", "published_exp512_candidate",
               "candidate_vs_published_exp512"]
    arrays = {profile[0]: [] for profile in PROFILES}
    physics_cache, reference_cache, physics_records, lineage = {}, {}, [], []
    basis_records = []
    global_position = 0
    maximum_reference_difference = 0.0
    for arm_index, run in enumerate(runs):
        arm_visit = 0
        if (not run["complete_training_trace"] or run["training_forward_calls"] != 32
                or run["status"] != "completed" or run["model_configuration"]["grid"] != grid):
            raise ValueError("incomplete original arm")
        path = args.input_root / f"seed{run['seed']}-{run['arm']}" / "training.jsonl"
        raw = checked(path, run["training_trace_sha256"], input_hashes)
        lines = raw.splitlines()
        if len(lines) != 32:
            raise ValueError("expected 32 original training rows per arm")
        for step, line in enumerate(lines):
            row = strict_json(line)
            parameters = row["physical_parameters"]
            if (row["step"] != step or len(row["model_sha256"]) != 64
                    or set(parameters) != {"mu", "sigma", "discount", "absolute_reset", "log_boundary"}
                    or parameters["mu"] != geometry_parameters["mu"]
                    or parameters["sigma"] != geometry_parameters["sigma"]):
                raise ValueError("row identity or shared spatial physics changed")
            key = json.dumps(parameters, sort_keys=True)
            reset = math.log(parameters["absolute_reset"]) - parameters["log_boundary"]
            if key not in physics_cache:
                physics_index = len(physics_records)
                physics_cache[key] = physics_index
                physics_records.append({"index": physics_index, "parameters": parameters, "reset_binary64_hex": reset.hex()})
                for profile in PROFILES:
                    spatial = generator(profile, parameters)
                    model = GradedJointModel(spatial, reset, grid["refractory"], parameters["discount"])
                    candidate_nodes, candidate_reset = model.perpetual()
                    reference = reference_values(parameters, reset, model.delay, grid, tuple(spatial.nodes))
                    weights = lifts[profile[0]][2]
                    candidate = np.r_[weights @ candidate_nodes, candidate_reset * reference["phase_factors"]]
                    migrated_finite = np.r_[weights @ reference["finite_nodes"], reference["finite_original"][17:]]
                    vectors = np.stack([reference["halfline_original"], reference["finite_original"], migrated_finite, candidate])
                    reference_cache[(physics_index, profile[0])] = vectors
                    basis_records.append((physics_index, profile[0], vectors,
                                          reference["halfline_original_mp80"], reference["finite_original_mp80"]))
            physics_index = physics_cache[key]
            states = row["states"]
            if (row["valid_mask"] != [[True] * len(states)]
                    or len(row["dt"]) != 1 or len(row["dt"][0]) != len(states)):
                raise ValueError("expected complete valid original posterior roster")
            lineage.append({"arm_index": arm_index, "seed": run["seed"], "arm": run["arm"],
                            "step": step, "episode_id": row["episode_id"], "model_sha256": row["model_sha256"],
                            "original_line_sha256": hashlib.sha256(line).hexdigest(),
                            "first_global_position": global_position, "positions": len(states),
                            "physics_index": physics_index})
            for position, state in enumerate(states):
                p = np.asarray(state["probability"], dtype=float)
                if (p.shape != (1, 25) or not np.isfinite(p).all() or p.min() < 0
                        or abs(float(p.sum()) - 1) > 5e-11):
                    raise ValueError("invalid retained posterior; no repair/renormalization allowed")
                p = p[0]
                original = published[global_position]
                if original[0] != arm_index or original[1] != arm_visit:
                    raise ValueError("published arm/visit identity disagrees with original journal")
                for profile in PROFILES:
                    a, b, c, d = reference_cache[(physics_index, profile[0])]
                    av, bv, cv, dv = [float(p @ v) for v in (a, b, c, d)]
                    migration, operator, truncation = cv - bv, dv - cv, bv - av
                    original_reference = float(original[5])
                    scale = max(1.0, abs(original_reference))
                    reference_delta = av - original_reference
                    maximum_reference_difference = max(maximum_reference_difference, abs(reference_delta))
                    if abs(reference_delta) > 5e-12 * scale:
                        raise ArithmeticError("new independent reference disagrees with published original reference")
                    residual = abs((dv - av) - (migration + operator + truncation))
                    arrays[profile[0]].append((global_position, arm_index, step, position, physics_index, reset,
                        av, bv, cv, dv, migration, operator, truncation, abs(dv - original_reference) / scale,
                        (abs(migration) + abs(operator) + abs(truncation) + abs(reference_delta)) / scale, residual,
                        p[16], float(p[:17] @ lifts[profile[0]][2][:, -1]),
                        p[16] * (d[16] - a[16]), float(p[2:17] @ (d[2:17] - a[2:17])),
                        original_reference, reference_delta, original[2], dv - original[2]))
                global_position += 1
                arm_visit += 1
        print(json.dumps({"completed_arm": arm_index + 1, "positions": global_position}), flush=True)
    if global_position != 14336 or len(lineage) != 384:
        raise ValueError("expected all 14336 posterior positions and 384 original rows")
    files, reports, profile_parts = {}, {}, {}
    for profile in PROFILES:
        name = profile[0]
        values_array = np.asarray(arrays[name], dtype=float)
        profile_parts[name] = []
        for part, start in enumerate(range(0, len(values_array), 7168)):
            chunk = values_array[start:start + 7168]
            path = out / f"ALL_POSTERIORS_{name}_part{part:03}.npz"
            np.savez_compressed(path, rows=chunk, columns=np.asarray(columns))
            files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            profile_parts[name].append({"file": path.name, "first_global_position": start,
                                        "positions": len(chunk), "bytes": path.stat().st_size,
                                        "sha256": files[path.name]})
        reports[name] = summaries(values_array, columns)
        records = [r for r in basis_records if r[1] == name]
        np.savez_compressed(out / f"BASIS_VALUES_{name}.npz", rows=np.asarray([r[2] for r in records]),
                            physics_index=np.asarray([r[0] for r in records]),
                            value_order=np.asarray(["halfline_original", "finite_original", "migrated_finite", "candidate_migrated"]))
        (out / f"BASIS_REFERENCE_MP80_{name}.json").write_text(json.dumps([
            {"physics_index": r[0], "profile": r[1], "halfline_original": r[3], "finite_original": r[4]}
            for r in records], indent=2) + "\n")
    (out / "LINEAGE.json").write_text(json.dumps(lineage, indent=2) + "\n")
    (out / "PHYSICS.json").write_text(json.dumps(physics_records, indent=2) + "\n")
    (out / "GEOMETRY.json").write_text(json.dumps(geometry, indent=2) + "\n")
    sources_after = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sources_before}
    unchanged = all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in input_hashes.items())
    if sources_before != sources_after or not unchanged:
        raise RuntimeError("source or original input changed during audit")
    for path in out.iterdir():
        if path.is_file():
            if path.stat().st_size > 1048576:
                raise RuntimeError(f"artifact exceeds declared 1 MiB publication bound: {path.name}")
            files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    result = {"identity": "right-tail-fixed-profile-retained-posterior-continuation-v1",
        "status": "HOLD_NO_GO", "persisted_source_commit": args.persisted_source_commit,
        "profiles": reports, "profile_parts": profile_parts,
        "maximum_artifact_bytes": 1048576,
        "posterior_positions": global_position, "training_rows": len(lineage),
        "unique_actual_physics_reset_laws": len(physics_records), "candidate_perpetual_calls": len(basis_records),
        "training_executions": 0, "filter_replays": 0, "dde_rollouts": 0,
        "original_scaled_continuation_gate": LIMIT, "threshold_unchanged": True,
        "primary_gate_reference": "original published #6189 exact62f corpus, hash checked and arm/visit joined",
        "arm_order_semantics": "Original root SUMMARY completion order, inherited by fa25828fc4faee625c10db1f70add43f0074ff41 audit_training_domain.py (Git blob04a650c5f676692f7ea316351bcbc3037f5cebcb) and enumerated by62f392a0ed953f2d04e9c62b4b243f5cceed2a98 audit_continuation.py. No lexical reordering.",
        "maximum_new_vs_published_reference_difference": maximum_reference_difference,
        "decomposition": "D-A=(D-C operator/reset)+(C-B migration)+(B-A upper nonreturning truncation); absolute sum prevents cancellation",
        "C_semantics": "Finite continuum evaluated on the migrated initial law, retaining the same unquantized deterministic reset as B. Only initial-law lift is applied in C.",
        "D_minus_C_semantics": "Combined discrete CTMC transport AND nodal randomization of the reset point; not a pure CTMC discretization error or a reset-matched comparison.",
        "whole_far_cells_definition": "original uniform cells whose left edge is at least .5 (indices2..15) plus tail16; crossing cell1 is excluded, not silently apportioned",
        "reference": "independent mpmath80 closed forms with explicit round-trip-decimal inputs, including actual journal mu=-.11999999999999998 rather than synthetic-.12; unquantized reset computed from actual recorded physics; tail retained to infinity",
        "upper_semantics": "permanently_active_nonreturning_escape",
        "input_sha256": input_hashes, "inputs_unchanged": unchanged,
        "source_sha256_before": sources_before, "source_sha256_after": sources_after,
        "output_sha256": files, "python": platform.python_version(), "numpy": np.__version__,
        "scipy": scipy.__version__, "mpmath": mpmath.__version__,
        "wall_seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu_started,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "limits": "Fixed-law backward continuation only. Not actual filtered future trajectories, independent efficacy, gradients, training or production admission. Near/far profile differences do not isolate a single mechanism."}
    (out / "SUMMARY.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"final": reports, "wall_seconds": result["wall_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
