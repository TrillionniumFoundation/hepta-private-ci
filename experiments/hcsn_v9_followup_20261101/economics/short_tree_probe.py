"""Controlled allocation/CPU tree, including adoption and a short-lived leaf.

This is an instrumentation fixture, not a model or aggregate-memory measurement.
Each node's own reported highwater is diagnostic, never a family peak.
"""

import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


MODULE = "experiments.hcsn_v9_followup_20261101.economics.short_tree_probe"
ALLOC_MIB = {"root": 8, "child": 12, "grandchild": 16, "short_leaf": 48}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--role", choices=tuple(ALLOC_MIB), default="root")
    parser.add_argument("--mode", choices=("waited", "adopted"), default="waited")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    began_ns = time.monotonic_ns()
    parent_before = os.getppid()
    allocation = bytearray(ALLOC_MIB[args.role] * 1024 * 1024)
    for index in range(0, len(allocation), 4096):
        allocation[index] = 1
    child = None
    roles = tuple(ALLOC_MIB)
    if args.role != "short_leaf":
        child = subprocess.Popen([
            sys.executable, "-m", MODULE, "--out", str(args.out),
            "--role", roles[roles.index(args.role) + 1], "--mode", args.mode,
        ])
    begin_cpu = time.process_time()
    checksum = 0
    while time.process_time() - begin_cpu < 0.015:
        checksum = (checksum * 48271 + 1) % 2147483647
    waits = []
    if child and (args.mode == "waited" or args.role == "grandchild"):
        _, status, measured = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
        waits.append({
            "pid": child.pid, "exit_code": child.returncode,
            "cpu_seconds": measured.ru_utime + measured.ru_stime,
            "largest_single_process_highwater_bytes": measured.ru_maxrss * 1024,
        })
    measured = resource.getrusage(resource.RUSAGE_SELF)
    record = {
        "role": args.role, "mode": args.mode, "pid": os.getpid(),
        "parent_before": parent_before, "parent_after": os.getppid(),
        "begin_monotonic_ns": began_ns, "end_monotonic_ns": time.monotonic_ns(),
        "allocated_touched_bytes": len(allocation), "checksum": checksum,
        "self_cpu_seconds": measured.ru_utime + measured.ru_stime,
        "self_highwater_diagnostic_bytes": measured.ru_maxrss * 1024,
        "spawned_pid": child.pid if child else None, "waited_children": waits,
        "family_peak_bytes": None, "fixture_not_model": True,
    }
    with (args.out / f"{args.role}.json").open("x") as handle:
        handle.write(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    main()
