"""Independent standard-library association of real joint-fit worker receipts."""

import argparse
import hashlib
import json
from pathlib import Path


def audit(run, receipts):
    checks, failures, inner = 0, [], 0.

    def check(ok, label):
        nonlocal checks
        checks += 1
        if not ok:
            failures.append(label)

    models = json.loads((run/"CANDIDATES.json").read_text())["models"]
    outer = json.loads((receipts/"training_batch001/RECEIPT.json").read_text())
    check(outer["task_success"] and outer["complete_task_cpu_coverage"] and outer["source_unchanged_through_collection"], "outer complete successful worker")
    for item in models:
        task, family, seed = item["task"], item["family"], item["seed"]
        path = receipts/"per_fit001"/f"{task}-{family}-{seed}"
        record = json.loads((path/"RECEIPT.json").read_text())
        config = json.loads((path/"CONFIG.json").read_text())
        supervision = json.loads((path/"SUPERVISION.json").read_text())
        command = record["command"]
        check(command[command.index("--task")+1] == task and command[command.index("--family")+1] == family and command[command.index("--seed")+1] == str(seed), "actual executed task/family/seed")
        check(record["task_success"] and record["complete_task_cpu_coverage"] and record["enclosing_supervisor_exit_code"] == 0, "successful complete fit process family")
        check(record["source_unchanged_through_collection"] is True and config["timeout"] == 180., "original source and declared timeout")
        check(hashlib.sha256((path/"SUPERVISION.json").read_bytes()).hexdigest() == record["supervision_sha256"], "original supervisor record bytes")
        check(supervision["all_waitable_children_collected"] and supervision["complete_task_cpu_coverage"], "all waited descendants accounted")
        check(outer["monotonic_begin_ns"] <= record["monotonic_begin_ns"] < record["monotonic_end_ns"] <= outer["monotonic_end_ns"], "fit envelope lies inside enclosing batch")
        inner += record["complete_supervisor_wait4"]["cpu_seconds"]
    enclosing = outer["complete_supervisor_wait4"]["cpu_seconds"]
    check(len(models) == 36 and 0 < inner <= enclosing, "36 nested fits and nonoverlapping CPU coverage")
    return {"checks": checks, "all_checks_passed": not failures, "failed_examples": failures,
            "fits": len(models), "complete_enclosing_batch_cpu_seconds": enclosing,
            "nested_fit_cpu_seconds_already_included": inner,
            "scope": "Actual fit command/exit/supervision/time envelope association; inner fit costs must not be added to enclosing CPU"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--receipts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    value = audit(args.run, args.receipts)
    with args.out.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
    print(json.dumps(value))
    raise SystemExit(0 if value["all_checks_passed"] else 1)
