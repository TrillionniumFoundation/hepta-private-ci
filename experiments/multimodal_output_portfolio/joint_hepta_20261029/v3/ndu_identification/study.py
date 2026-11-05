"""Run the frozen 18-task mechanism study without Monte Carlo selection."""
import argparse
from dataclasses import asdict
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import time
from .model import Task, evaluate, planner


def run(output):
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise FileExistsError("Use an empty evidence directory; prior runs are immutable")
    directory = Path(__file__).parent
    protocol_bytes = (directory/"protocol.json").read_bytes()
    protocol = json.loads(protocol_bytes)
    (destination/"protocol.json").write_bytes(protocol_bytes)
    source_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sorted(directory.glob("*.py"))}
    started = time.perf_counter(), time.process_time()
    rows, leaf_records = [], []
    for deadline in protocol["deadline_grid"]:
        for fee in protocol["launch_fee_grid"]:
            task = Task(deadline, fee, protocol["rho"], protocol["max_probes"])
            case = f"deadline_{deadline}_fee_{fee}"
            values = {}
            for mode in protocol["policies"]:
                plan_start = time.perf_counter(), time.process_time()
                policy, solve = planner(task, mode)
                planned, _, root_q = solve(F(1, 2), deadline, 1 if mode == "myopic" else task.max_probes)
                plan_wall, plan_cpu = time.perf_counter()-plan_start[0], time.process_time()-plan_start[1]
                result = evaluate(task, policy, label_only=mode == "label_only")
                for leaf in result.pop("leaves"):
                    leaf_records.append({"case": case, "policy": mode, **leaf})
                row = {"case": case, "task": asdict(task), "policy": mode,
                       "root_action": policy(F(1, 2), deadline, task.max_probes),
                       "planned_value": planned, "root_action_values": root_q,
                       "planner_wall_seconds": plan_wall, "planner_cpu_seconds": plan_cpu,
                       "states_visited": solve.cache_info().currsize, **result}
                rows.append(row)
                values[mode] = result["utility"]
            for row in rows[-len(protocol["policies"]):]:
                row["gain_over_no_probe"] = row["utility"]-values["no_probe"]
                row["gap_to_exact"] = values["exact"]-row["utility"]
                if row["gap_to_exact"] < -1e-12:
                    raise ArithmeticError("A feasible policy exceeded exact DP")
    raw = "".join(json.dumps(x, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n" for x in leaf_records)
    (destination/"trajectories.jsonl").write_text(raw)
    payload = {"schema": "ndu-identification.study.v1", "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
               "source_sha256": source_hashes, "trajectory_sha256": hashlib.sha256(raw.encode()).hexdigest(),
               "case_count": 18, "policy_cells": len(rows), "enumerated_leaves": len(leaf_records),
               "clock_scope": "simulated durations; hardware execution timing recorded only as metadata",
               "precision": "rational probability/likelihood/posterior; ordinary float discount and utility",
               "rows": rows, "wall_seconds": time.perf_counter()-started[0],
               "cpu_seconds": time.process_time()-started[1]}
    target = destination/"results.json"
    target.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n")
    print(json.dumps({"results": str(target), "cases": 18, "cells": len(rows), "leaves": len(leaf_records),
                      "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    run(parser.parse_args().output)
