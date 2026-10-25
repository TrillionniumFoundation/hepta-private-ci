"""Read-only arithmetic, replay and resource analysis of a sealed V2 run.

Does not import the solver, training-state implementation or evaluator and does
not open final-label payloads. This checks saved evidence, never retrains models.
"""

import argparse
from collections import defaultdict
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def arrays(path):
    with np.load(path, allow_pickle=False) as archive:
        return {name: archive[name].copy() for name in archive.files}


def tensor_sha(value):
    value = np.ascontiguousarray(value)
    return hashlib.sha256(canonical([value.dtype.str, list(value.shape)])
                          + value.tobytes()).hexdigest()


def checkpoint(path):
    metadata = json.loads((path / "manifest.json").read_bytes())
    tensors = arrays(path / "state.npz")
    assert sha(path / "state.npz") == metadata["payload_sha256"]
    assert {key: tensor_sha(value) for key, value in tensors.items()} == metadata["tensor_sha256"]
    vector = np.concatenate([tensors[group + "__" + name].ravel()
                             for group in ("theta", "m", "v")
                             for name in metadata["parameter_names"]])
    base = {key: value for key, value in metadata.items() if key not in
            ("state_sha256", "payload_sha256", "tensor_sha256", "retained_tensor_bytes", "authority")}
    digest = hashlib.sha256(canonical(base) + bytes.fromhex(tensor_sha(vector))).hexdigest()
    assert digest == metadata["state_sha256"] and vector.nbytes == metadata["retained_tensor_bytes"]
    return metadata, vector, tensors


def costs(fields, actions, target, h, price):
    difference = fields - target
    weights = np.r_[np.full(len(actions), h), 1.0]
    current = 0.5 * float(weights @ difference[:, 0] ** 2)
    forgetting = 0.5 * float(weights @ np.maximum(difference[:, 1], 0) ** 2)
    effort = 0.5 * h * price * float(np.square(actions).sum())
    symmetric = 0.5 * float(weights @ np.square(difference).sum(axis=1)) + effort
    return {"total": current + forgetting + effort, "current": current,
            "forgetting": forgetting, "effort": effort,
            "tracking": current + forgetting,
            "maximum_old_excess": float(difference[:, 1].max()),
            "terminal_old_excess": float(difference[-1, 1]),
            "old_violation_steps": int(np.count_nonzero(difference[:, 1] > 1e-12)),
            "legacy_symmetric_total": symmetric}


def analyze(run_directory, output):
    root = Path(run_directory)
    runs = json.loads((root / "runs.json").read_bytes())
    seal = json.loads((root / "pre_evaluation_seal.json").read_bytes())
    plan, h, price = runs["protocol"], runs["protocol"]["h"], runs["protocol"]["effort_price"]
    assert seal["final_labels_opened"] is False and runs["final_labels_opened"] is False
    actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()
              and p.name != "pre_evaluation_seal.json"}
    assert actual == set(seal["files"])
    for name, identity in seal["files"].items():
        path = root / name
        assert path.stat().st_size == identity["bytes"] and sha(path) == identity["sha256"], name
    maximum_cost_error, rows, replays, plan_rows = 0.0, [], [], []
    records = runs["records"]
    for record in records:
        if record["status"] != "completed":
            rows.append({key: record[key] for key in ("run_id", "status", "error")})
            continue
        trajectory = arrays(root / record["paths"]["trajectory"])
        tangent = arrays(root / record["paths"]["tangent"])
        controller = arrays(root / record["paths"]["controller"])
        nonlinear_cost = costs(trajectory["fields"], trajectory["actions"], controller["target"], h, price)
        tangent_cost = costs(tangent["fields"], tangent["actions"], controller["target"], h, price)
        for calculated, stored in ((nonlinear_cost, record), (tangent_cost, record["tangent"])):
            for key, value in calculated.items():
                expected = (stored["legacy_symmetric_cost"]["total"] if key == "legacy_symmetric_total"
                            else stored["cost"][key])
                error = abs(value - expected)
                maximum_cost_error = max(maximum_cost_error, error)
                assert error <= 1e-12 * (1 + abs(expected)), (record["run_id"], key)
        meta, vector, _ = checkpoint(root / record["paths"]["checkpoint"])
        assert np.array_equal(vector, trajectory["states"][-1])
        assert meta["step_count"] == plan["warmup_steps"] + plan["horizon"]
        assert meta["sampler_draw_count"] == 0
        solver = json.loads((root / record["paths"]["solver"]).read_bytes())
        assert len(solver) == plan["horizon"]
        for item in solver:
            plan_rows.append({**item, "run_id": record["run_id"], "policy": record["policy"],
                              "head": record["head"], "mask": record["mask"]})
        rows.append({**{key: record[key] for key in ("run_id", "seed", "head", "mask", "policy", "status")},
                     "nonlinear": nonlinear_cost, "tangent": tangent_cost,
                     "nonlinear_minus_tangent_J": nonlinear_cost["total"] - tangent_cost["total"],
                     "maximum_charged_closure_forcing": float(tangent["charged_closure_forcing"].max()),
                     "probe_initial": record["probe_initial"], "probe_final": record["probe_final"],
                     "rollout_wall_seconds": record["wall_ns"] / 1e9,
                     "rollout_cpu_seconds": record["cpu_ns"] / 1e9,
                     "controller_build_wall_seconds": record["policy_build_wall_ns"] / 1e9,
                     "online_plan_wall_seconds": sum(x["plan_wall_ns"] for x in solver) / 1e9,
                     "maximum_solver_iterations": max(x["iterations"] for x in solver),
                     "maximum_solver_gap": max(x["optimality_gap_bound"] for x in solver),
                     "combined_gap_interval": record["tangent"]["combined_information_policy_gap_interval"]})
        if record["mask"] != "all" or record["policy"] != "loss2":
            continue
        receipt_rows = json.loads((root / record["paths"]["receipts"]).read_bytes())
        for name, start in (("whole", 0), ("midpoint", plan["horizon"] // 2)):
            directory = root / record["paths"]["recovery"] / name
            recovered = arrays(directory / "replayed.npz")
            for key in ("states", "observations", "actions"):
                assert np.array_equal(recovered[key], trajectory[key][start:]), (record["run_id"], name, key)
            final_meta, final_vector, final_tensors = checkpoint(directory / "restored-final")
            initial_meta, initial_vector, _ = checkpoint(directory / "input-state")
            assert np.array_equal(initial_vector, trajectory["states"][start])
            assert initial_meta["step_count"] == plan["warmup_steps"] + start
            assert final_meta == meta and np.array_equal(final_vector, vector)
            result = json.loads((directory / "result.json").read_bytes())
            assert result["receipts"] == receipt_rows[start:]
            assert result["state_sha256"] == meta["state_sha256"]
            timing = {"wall_ns", "cpu_ns", "plan_wall_ns", "plan_cpu_ns"}
            clean = lambda values: [{k: v for k, v in x.items() if k not in timing} for x in values]
            assert clean(result["solver_records"]) == clean(solver[start:])
            job = json.loads((directory / "job.json").read_bytes())
            assert job["source_hashes"] == runs["sourcecode_hashes"]
            for item, expected in job["inputs"].items(): assert sha(directory / item) == expected
            replays.append({"run_id": record["run_id"], "segment": name, "start_step": initial_meta["step_count"],
                            "final_step": final_meta["step_count"], "states_observations_actions_bitwise": True,
                            "complete_final_manifest_identical": True, "transition_receipts_identical": True,
                            "solver_arithmetic_records_identical_excluding_timing": True})
    groups = []
    for head, mask, policy in itertools.product(plan["head_modes"], plan["action_masks"], plan["policies"]):
        selected = [x for x in rows if x["status"] == "completed"
                    and (x["head"], x["mask"], x["policy"]) == (head, mask, policy)]
        if len(selected) != len(plan["seeds"]):
            groups.append({"head": head, "mask": mask, "policy": policy, "incomplete": True});continue
        row = {"head": head, "mask": mask, "policy": policy, "fixed_seeds": plan["seeds"]}
        for kind in ("nonlinear", "tangent"):
            row[kind] = {key: float(np.mean([x[kind][key] for x in selected])) for key in selected[0][kind]}
        for key in ("maximum_charged_closure_forcing", "rollout_wall_seconds", "rollout_cpu_seconds",
                    "controller_build_wall_seconds", "online_plan_wall_seconds"):
            row[key] = float(np.mean([x[key] for x in selected]))
        row["probe_initial"] = np.mean([x["probe_initial"] for x in selected], axis=0).tolist()
        row["probe_final"] = np.mean([x["probe_final"] for x in selected], axis=0).tolist()
        groups.append(row)
    comparisons = []
    for seed, head, mask in itertools.product(plan["seeds"], plan["head_modes"], plan["action_masks"]):
        policies = {x["policy"]: x for x in rows if x["status"] == "completed"
                    and (x["seed"], x["head"], x["mask"]) == (seed, head, mask)}
        for left, right in (("loss2", "myopic"), ("loss2", "zero"),
                            ("loss2", "symmetric_loss2"), ("extended", "loss2"), ("full", "loss2")):
            if left not in policies or right not in policies: continue
            a, b = policies[left], policies[right]
            comparisons.append({"seed": seed, "head": head, "mask": mask, "left": left, "right": right,
                "J_difference": a["nonlinear"]["total"] - b["nonlinear"]["total"],
                "J_relative_reduction": 1 - a["nonlinear"]["total"] / b["nonlinear"]["total"],
                "current_probe_final_difference": a["probe_final"][0] - b["probe_final"][0],
                "old_probe_final_difference": a["probe_final"][1] - b["probe_final"][1]})
    qualified = [x for x in plan_rows if x["policy"] != "zero"]
    assert all(x["converged"] and x["optimality_gap_bound"] <= plan["solver"]["gap_tolerance"] for x in qualified)
    successful = [x for x in records if x["status"] == "completed"]
    resource = {"run_execution": runs["execution"], "environment": runs["environment"],
        "warmup_wall_seconds": sum(x["warmup"]["wall_ns"] for x in runs["initial_order"] if x["status"] == "completed") / 1e9,
        "reference_derivatives_wall_seconds": sum(x["build_wall_ns"] for x in runs["references"] if x["status"] == "completed") / 1e9,
        "controller_build_wall_seconds": sum(x["policy_build_wall_ns"] for x in successful) / 1e9,
        "nonlinear_rollout_wall_seconds": sum(x["wall_ns"] for x in successful) / 1e9,
        "nonlinear_rollout_cpu_seconds": sum(x["cpu_ns"] for x in successful) / 1e9,
        "online_plan_wall_seconds": sum(x["plan_wall_ns"] for x in plan_rows) / 1e9,
        "tangent_diagnostics_wall_seconds": sum(x["tangent_diagnostic_time"]["wall_ns"] for x in successful) / 1e9,
        "cold_process_wall_seconds": sum(y["wall_ns_including_process"] for x in successful if "recovery" in x
                                          for y in x["recovery"]["checks"]) / 1e9,
        "prediction_roundtrip_wall_seconds": sum(x["prediction_and_serving_roundtrip_wall_ns"] for x in successful) / 1e9,
        "sealed_files": len(seal["files"]), "sealed_bytes": sum(x["bytes"] for x in seal["files"].values()),
        "qualification": "timings can nest and are not an exhaustive additive accounting; parent timer ends before final seal; energy and replay-child CPU unmeasured"}
    output_value = {"schema": "hepta.cell-retention-math-resource-replay-analysis.v2",
        "source_sha256": sha(__file__), "pre_evaluation_seal_sha256": sha(root / "pre_evaluation_seal.json"),
        "run_summary_sha256": sha(root / "runs.json"), "registered_conditions": len(records),
        "completed": len(successful), "final_labels_opened": False, "main_solver_imported": False,
        "maximum_recomputed_cost_abs_error": maximum_cost_error, "per_run": rows,
        "fixed_seed_means": groups, "paired_comparisons": comparisons,
        "replay_checks": replays, "resources": resource,
        "qualified_nonlinear_solver_plans": len(qualified),
        "maximum_nonlinear_solver_iterations": max(x["iterations"] for x in qualified),
        "maximum_nonlinear_solver_gap_bound": max(x["optimality_gap_bound"] for x in qualified),
        "oracle_intervals": [{"initial_id": x["initial_id"], "values": x.get("oracle_intervals")} for x in runs["references"]],
        "interpretation": ["Single-sided soft penalty does not ensure hard retention feasibility.",
            "Current loss is still symmetric target tracking, so not all proxy misalignment has been removed.",
            "Means describe these three fixed fitted seeds; no population uncertainty is inferred.",
            "Closure forcing is measured in common loss units along each policy's own trajectory."]}
    Path(output).write_bytes(canonical(output_value) + b"\n")
    return output_value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = analyze(args.run, args.output)
    print(json.dumps({key: result[key] for key in ("completed", "maximum_recomputed_cost_abs_error",
          "qualified_nonlinear_solver_plans", "maximum_nonlinear_solver_gap_bound", "resources")}, indent=2))
