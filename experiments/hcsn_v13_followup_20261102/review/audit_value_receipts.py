"""Associate real value-fit worker envelopes and retain the pre-VAL failure."""

import argparse
import hashlib
import json
from pathlib import Path


def audit(root, run, receipts):
    checks, failed = 0, []

    def check(ok, label):
        nonlocal checks
        checks += 1
        if not ok:
            failed.append(label)

    stages, total = {}, 0.
    for name in ("prepare001", "prepare002", "batch001", "freeze001", "audit_candidates001"):
        directory = receipts/name
        record = json.loads((directory/"RECEIPT.json").read_text())
        check(record["complete_task_cpu_coverage"] and record["source_unchanged_through_collection"], "complete stable stage envelope")
        check(hashlib.sha256((directory/"SUPERVISION.json").read_bytes()).hexdigest() == record["supervision_sha256"], "stage supervision bytes")
        check(record["task_success"] is (name != "prepare001"), "retained failure and actual successful stages")
        seconds = record["complete_supervisor_wait4"]["cpu_seconds"]
        total += seconds
        stages[name] = {"task_success": record["task_success"], "cpu_seconds": seconds}
    check("Required content/source bytes are absent" in (receipts/"prepare001/stderr.log").read_text(), "actual retained publication-gap failure")
    outer = json.loads((receipts/"batch001/RECEIPT.json").read_text())
    batch = json.loads((run/"BATCH.json").read_text())
    expected = {(m["task"], m["family"], m["seed"]) for m in json.loads((run/"CANDIDATES.json").read_text())["models"]}
    observed, inner = set(), 0.
    for row in batch["rows"]:
        key = row["task"], row["family"], row["seed"]
        check(key not in observed and key in expected, "unique actual value-fit roster")
        observed.add(key)
        path = root/row["receipt"]
        record = json.loads(path.read_text())
        check(row["exit_code"] == 0 and record["task_success"] and record["complete_task_cpu_coverage"], "actual complete successful value-fit worker")
        command = record["command"]
        check(command[command.index("--task")+1] == key[0] and command[command.index("--family")+1] == key[1] and command[command.index("--seed")+1] == str(key[2]), "actual executed value model task/family/seed")
        check(outer["monotonic_begin_ns"] <= record["monotonic_begin_ns"] < record["monotonic_end_ns"] <= outer["monotonic_end_ns"], "value-fit contained in batch envelope")
        check(hashlib.sha256((path.parent/"SUPERVISION.json").read_bytes()).hexdigest() == record["supervision_sha256"], "per-fit supervisor raw bytes")
        inner += record["complete_supervisor_wait4"]["cpu_seconds"]
    check(observed == expected and len(observed) == 36, "complete thirty-six value fits")
    check(0 < inner <= outer["complete_supervisor_wait4"]["cpu_seconds"], "inner CPU already included once")
    return {"checks": checks, "all_checks_passed": not failed, "failed_examples": failed,
            "stages": stages, "disjoint_stage_cpu_seconds": total,
            "nested_fit_cpu_seconds_already_included": inner,
            "scope": "Actual command/exit/CPU and retained pre-VAL source-publication failure; excludes separate independent reviews and TEST execution"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--receipts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root, args.run, args.receipts)
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result))
    raise SystemExit(0 if result["all_checks_passed"] else 1)
