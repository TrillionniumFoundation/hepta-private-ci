"""Run all five authorized V4 research comparisons without withheld labels."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import numpy as np

from cell_field_action_io import deny_withheld_labels, environment, save_arrays, source_hashes, write_json
from cell_field_experiments_v4 import fixed_anchor, pressure_census
from cell_field_io_v4 import load_task, seal_run
from cell_field_mpc_v4 import execute_policy
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead, normalize_features


def warm_state(task, seed, mode, inputs, output, hashes):
    plan, split = inputs["plan"], inputs["split"]
    contexts = {name: dataset_digest(*split[name]) for name in ("old_train", "current_train")}
    bindings = {"protocol_sha256": inputs["protocol_sha256"], "task": task, "seed": seed,
        "head_mode": mode, "feature_identity": inputs["feature_report"]["feature_identity"],
        "sources_sha256": inputs["input_hashes"]["sources.json"], "executed_code_sha256": hashes}
    state = CellTrainingState(NumpyCellHead(8, 4, mode, seed=seed), bindings=bindings,
        protocol=plan["optimizer"], seed=seed, contexts=contexts, active_context="old_train")
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    vectors, receipts = [state.vector()], []
    for _ in range(plan["warmup_steps"]):
        receipts.append(state.advance(*split["old_train"]))
        vectors.append(state.vector())
    state.select_context("current_train")
    old_x, old_y = split["old_probe"]
    anchor = float(state.head.loss_gradients(normalize_features(old_x), old_y, 0.0)[0])
    record = {"status": "completed", "old_anchor": anchor, "state_sha256": state.digest(),
              "cpu_ns": time.process_time_ns() - cpu, "wall_ns": time.perf_counter_ns() - began}
    state.save(output / "checkpoint")
    save_arrays(output / "warmup.npz", {"states": np.asarray(vectors),
        "probabilities": state.head.predict_proba(inputs["projected"])})
    write_json(output / "receipts.json", receipts)
    write_json(output / "result.json", record)
    return state, record


def execute(data, features, protocol, output):
    sys.addaudithook(deny_withheld_labels)
    data, features, protocol, output = map(Path, (data, features, protocol, output))
    plan = json.loads(protocol.read_bytes())
    output.mkdir(parents=True, exist_ok=False)
    hashes = source_hashes()
    write_json(output / "executed_source.json", hashes)
    write_json(output / "protocol.json", plan)
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    summary = {"schema": "hepta.cell-field-joint-run.v4", "started_at": datetime.now(timezone.utc).isoformat(),
        "fits": [], "registered_fits": 12, "registered_fixed_branches": 1764,
        "registered_mpc_policies": 84, "tasks": {}, "authority": "DENY_ALL", "production_authority": False}
    for task in plan["tasks"]:
        inputs = load_task(data / task, features / task, protocol, task)
        split, projected = inputs["split"], inputs["projected"]
        indices = np.asarray([row["index"] for row in inputs["sources"] if row["role"] == "old_test"])
        save_arrays(output / task / "projected.npz", {"features": projected, "projection": inputs["projection"]})
        save_arrays(output / task / "training.npz", {role + "_" + suffix: value
            for role, pair in split.items() for suffix, value in zip(("x", "y"), pair)})
        write_json(output / task / "inputs.json", {"input_hashes": inputs["input_hashes"],
            "feature_report": inputs["feature_report"], "retention_indices": indices.tolist(),
            "sources": inputs["sources"], "data_receipt": inputs["receipt"]})
        summary["tasks"][task] = {"rows": len(projected), "feature_report": inputs["feature_report"]}
        for seed in plan["seeds"]:
            for mode in plan["head_modes"]:
                fit_id = f"{task}-seed{seed}-{mode}"
                directory = output / task / f"seed{seed}-{mode}"
                row = {"fit_id": fit_id, "task": task, "seed": seed, "head": mode,
                       "status": "failed", "fixed": [], "mpc": []}
                summary["fits"].append(row)
                try:
                    warmup, warm = warm_state(task, seed, mode, inputs, directory / "warmup", hashes)
                    row["warmup"] = warm
                    baseline, offset = warmup.clone(), 0
                    for target in plan["anchor_offsets"]:
                        while offset < target:
                            baseline.advance(*split["current_train"])
                            offset += 1
                        try:
                            item = fixed_anchor(baseline, split, plan, projected, indices,
                                warm["old_anchor"], directory / f"fixed/anchor{target}")
                        except Exception as error:
                            item = {"status": "unavailable", "registered": 49, "completed": 0,
                                    "error": {"type": type(error).__name__, "message": str(error)}}
                        row["fixed"].append({"offset": target, **item})
                    try:
                        row["pressure"] = pressure_census(warmup, split, plan, projected, indices,
                                                           directory / "pressure")
                    except Exception as error:
                        row["pressure"] = {"status": "unavailable", "error": {
                            "type": type(error).__name__, "message": str(error)}}
                    for policy in plan["mpc"]["policies"]:
                        result = execute_policy(warmup, split, plan, projected, warm["old_anchor"],
                                                policy, directory / "mpc" / policy)
                        row["mpc"].append({key: result[key] for key in
                            ("policy", "status", "cpu_ns", "wall_ns", "completed_steps", "error")})
                    row["status"] = ("completed" if all(a["status"] == "completed" for a in row["fixed"])
                        and all(a["status"] == "completed" for a in row["mpc"])
                        and "search" in row["pressure"] else "completed_with_unavailable_conditions")
                except Exception as error:
                    row["error"] = {"type": type(error).__name__, "message": str(error)}
                write_json(directory / "fit.json", row)
                write_json(output / "run.json", summary)
                print(json.dumps({"fit": fit_id, "status": row["status"],
                    "fixed_completed": sum(a["completed"] for a in row["fixed"]),
                    "mpc_completed": sum(a["status"] == "completed" for a in row["mpc"]),
                    "error": row.get("error")}), flush=True)
    summary.update(cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - began,
                   environment=environment(), completed_at=datetime.now(timezone.utc).isoformat())
    write_json(output / "run.json", summary)
    seal_run(output, protocol)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "features", "protocol", "output"):
        parser.add_argument("--" + name, required=True)
    execute(**vars(parser.parse_args()))
