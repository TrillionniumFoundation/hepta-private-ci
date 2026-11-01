"""Actual CPU-consuming process tree; explicitly a cost-instrument fixture."""

import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


MODULE = "experiments.hcsn_v8_execution_20261101.economics.process_tree_probe"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--role", choices=("root", "child", "grandchild"), default="root")
    parser.add_argument("--orphan", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    source_ns = time.monotonic_ns()
    child = None
    if args.role != "grandchild":
        next_role = "child" if args.role == "root" else "grandchild"
        child = subprocess.Popen([sys.executable, "-m", MODULE, "--out", str(args.out), "--role", next_role])
    burn_begin = time.process_time()
    checksum = 1
    while time.process_time() - burn_begin < 0.08:
        checksum = (checksum * 48271) % 2147483647
    child_wait = None
    if child and not (args.role == "root" and args.orphan):
        _, status, measured = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
        child_wait = {"exit_code": child.returncode,
                      "cpu_seconds": measured.ru_utime + measured.ru_stime}
    if args.role == "root":
        print(json.dumps({"kind": "episode_prediction", "episode_id": "cpu-tree-fixture", "answer": checksum}), flush=True)
        flushed_ns = time.monotonic_ns()
        print(json.dumps({"kind": "episode_output", "episode_id": "cpu-tree-fixture",
                          "source_monotonic_ns": source_ns, "output_flush_monotonic_ns": flushed_ns}), flush=True)
    measured = resource.getrusage(resource.RUSAGE_SELF)
    record = {"role": args.role, "pid": os.getpid(), "self_cpu_seconds": measured.ru_utime + measured.ru_stime,
              "child_pid": child.pid if child else None, "child_wait": child_wait,
              "burn_cpu_seconds": time.process_time() - burn_begin,
              "orphaned_child_intentionally": bool(child and args.role == "root" and args.orphan),
              "fixture_not_model": True}
    (args.out / (args.role + ".json")).write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    main()
