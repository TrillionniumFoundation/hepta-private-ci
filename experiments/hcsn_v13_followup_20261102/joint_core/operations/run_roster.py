"""Bounded two-worker launcher; per-fit envelopes are nested in outer receipt."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--receipts", type=Path, required=True)
    parser.add_argument("--source-remote-head", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_remote_head):
        raise ValueError("Explicit published source identity required")
    args.receipts.mkdir(parents=True, exist_ok=False)
    plan = json.loads((args.run/"PLAN.json").read_text())
    p = plan["protocol"]
    roster = [{"task": task, "family": family, "seed": seed}
              for task in p["tasks"] for seed in p["seeds"] for family in p["families"]]
    assert len(roster) == p["fits"] == 36
    (args.receipts/"ROSTER.json").write_text(json.dumps({"plan_sha256": sha(args.run/"PLAN.json"),
        "source_remote_head": args.source_remote_head, "launcher_source_sha256": sha(Path(__file__)),
        "maximum_parallel_fit_workers": 2, "models": roster}, indent=2)+"\n")

    def execute(item):
        label = "-".join(str(item[k]) for k in ("task", "family", "seed"))
        command = [sys.executable, "-m", "experiments.hcsn_v8_execution_20261101.economics.worker_cost",
                   "--out", str(args.receipts/label), "--timeout", str(p["per_fit_outer_timeout_seconds"]),
                   "--sample-interval", "0.5", "--", sys.executable, "-m",
                   "experiments.hcsn_v13_followup_20261102.joint_core.campaign", "fit", "--run", str(args.run)]
        for key, value in item.items():
            command.extend(("--"+key, str(value)))
        began = time.monotonic_ns()
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        (args.receipts/(label+"-launcher.log")).write_text(result.stdout+result.stderr)
        row = {**item, "launch_monotonic_ns": began, "wait_monotonic_ns": time.monotonic_ns(),
               "wrapper_exit_code": result.returncode, "receipt": str(args.receipts/label/"RECEIPT.json")}
        print(json.dumps(row), flush=True)
        return row

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, roster))
    (args.receipts/"RESULTS.json").write_text(json.dumps({"models": results,
        "all_fit_wrappers_exited_zero": all(r["wrapper_exit_code"] == 0 for r in results),
        "nested_cost_rule": "Per-fit envelope CPU is already inside this launcher's enclosing worker; add the outer global receipt once."}, indent=2)+"\n")
    return 0 if all(r["wrapper_exit_code"] == 0 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
