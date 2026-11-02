"""Stdlib-only fixed-roster orchestration; no candidate or data-role logic."""

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def main(run, receipts, out):
    plan = json.loads((run / "PLAN.json").read_text())
    protocol = plan["protocol"]
    roster = [(task, family, seed) for task in protocol["tasks"]
              for family in protocol["families"] for seed in protocol["seeds"]]
    if len(roster) != 36 or len(set(roster)) != 36:
        raise RuntimeError("The published complete reader roster is required")
    receipts.mkdir(parents=True, exist_ok=False)
    source_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    started = time.monotonic_ns()

    def fit(item):
        task, family, seed = item
        name = f"{task}-{family}-{seed}"
        command = [sys.executable, "-m", "experiments.hcsn_v8_execution_20261101.economics.worker_cost",
            "--out", str(receipts / name), "--timeout", str(protocol["per_fit_outer_timeout_seconds"]),
            "--sample-interval", ".5", "--", sys.executable, "-m",
            "experiments.hcsn_v13_followup_20261102.control.value_fit", "fit", "--run", str(run),
            "--task", task, "--family", family, "--seed", str(seed)]
        with (receipts / (name + ".log")).open("xb") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        return {"task": task, "family": family, "seed": seed, "exit_code": result.returncode,
                "receipt": str(receipts / name / "RECEIPT.json")}

    rows, failed, iterator = [], False, iter(roster)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = {pool.submit(fit, next(iterator)) for _ in range(2)}
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                row = future.result(); rows.append(row)
                failed |= row["exit_code"] != 0
                print(json.dumps({"completed": len(rows), **row}), flush=True)
            while not failed and len(pending) < 2:
                item = next(iterator, None)
                if item is None: break
                pending.add(pool.submit(fit, item))
    report = {"schema": "hcsn-v13-value-fit-orchestration.v1", "rows": rows, "all_36_passed": len(rows) == 36 and not failed,
              "max_parallel_fits": 2, "elapsed_monotonic_seconds": (time.monotonic_ns()-started)/1e9,
              "plan_sha256": hashlib.sha256((run / "PLAN.json").read_bytes()).hexdigest(),
              "source_sha256_at_start": source_sha,
              "source_unchanged": hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == source_sha,
              "cost_rule": "This driver is itself enclosed by worker_cost; per-fit envelopes are nested diagnostics, not additional batch CPU."}
    with out.open("x") as stream: json.dump(report, stream, indent=2); stream.write("\n")
    return 0 if report["all_36_passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True); parser.add_argument("--receipts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); raise SystemExit(main(args.run, args.receipts, args.out))
