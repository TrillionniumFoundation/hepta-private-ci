#!/usr/bin/env python3
"""Short measurement-only calibration on owned, idle live process trees.

No models, tools, SSH or production settings are used. Children are started and
closed only through locally owned Popen handles. Cgroup files are read-only.
This is a calibration, not a benchmark result or an agent CPU comparison.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

from process_metrics import CgroupScope
from process_metrics import ProcessMetrics as V1
from process_metrics_v2 import ProcessMetrics as V2
from test_process_metrics_v2 import BRANCH
from test_process_metrics_v2 import TREE
from test_process_metrics_v2 import identities
from test_process_metrics_v2 import live_process


def own_cgroup():
    for line in Path("/proc/self/cgroup").read_text().splitlines():
        if line.startswith("0::"):
            return Path("/sys/fs/cgroup") / line[3:].lstrip("/")
    return None


def run(args):
    proc_pid = int(Path("/proc/self/stat").read_text().split("(", 1)[0])
    if proc_pid != os.getpid():
        raise RuntimeError("proc PID namespace differs from caller; calibration cannot run here")
    if args.seconds <= 0 or args.rounds < 1 or args.output.exists():
        raise ValueError("positive seconds/rounds and a new output file are required")
    root = Path(__file__).parent
    group = own_cgroup()
    report = {
        "schema": "hepta.process-metrics.calibration.v2",
        "host": {"platform": platform.platform(), "python": sys.version,
                 "cpu_count": os.cpu_count(), "observer_pid": os.getpid(),
                 "self_cgroup": str(group) if group else None},
        "scope": "owned calibration process descendants plus its explicit containing cgroup",
        "workload": "idle owned tree; includes non-main-thread child and grandchildren",
        "seconds_per_arm": args.seconds, "rounds": args.rounds,
        "maximum_observer_cpu_per_elapsed_second": args.max_observer_ratio,
        "source_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                          for name in ("process_metrics.py", "process_metrics_v2.py",
                                       "test_process_metrics_v2.py", Path(__file__).name)},
        "rows": [],
        "limits": ["No model, agent or runtime task executes in this calibration",
                   "A selected live cgroup may also contain its supervisor; selection is reported",
                   "Idle-tree calibration does not replace formal same-task measurement",
                   "Observer CPU is active sample call-thread CPU, including main-thread boundary samples",
                   "A 100ms wait after each sample is not a fixed 10Hz sampling clock"],
    }
    arms = [("v1_10ms", V1, 0.01), ("v2_10ms", V2, 0.01), ("v2_100ms", V2, 0.1)]
    with live_process(TREE) as (_, tree), live_process(BRANCH) as (_, extra):
        report["owned_fixture_pids"] = sorted({tree["root"], *tree["descendants"],
                                                extra["root"], *extra["descendants"]})
        expected = set(report["owned_fixture_pids"]) | {os.getpid()}
        reference = None
        for round_index in range(args.rounds):
            order = arms if round_index % 2 == 0 else list(reversed(arms))
            for name, implementation, interval in order:
                cpu_begin = time.process_time()
                collector = implementation(root_pids=[os.getpid()], extra_pids=[extra["root"]],
                    cgroup_paths=[CgroupScope(group)] if group else [], sample_interval=interval).start()
                time.sleep(args.seconds)
                metrics = collector.stop()
                process_cpu = time.process_time() - cpu_begin
                observed = identities(metrics)
                if reference is None:
                    reference = observed
                selected_pids = {row["pid"] for row in metrics["processes"]}
                sampling = metrics["sampling"]
                row = {
                    "round": round_index, "arm": name,
                    "selected_identities": sorted(observed),
                    "selected_pids": sorted(selected_pids),
                    "missing_owned_fixture_pids": sorted(expected - selected_pids),
                    "missing_vs_first_v1": sorted(reference - observed),
                    "added_vs_first_v1": sorted(observed - reference),
                    "same_selected_identities_as_first_v1": observed == reference,
                    "elapsed_seconds": metrics["elapsed_seconds"],
                    "observer_cpu_per_elapsed_second": sampling["observer_cpu_seconds"] / metrics["elapsed_seconds"],
                    "calibration_process_cpu_seconds": process_cpu,
                    "sampling": sampling, "coverage": metrics["coverage"],
                    "memory": metrics["memory"], "cpu": metrics["cpu"],
                }
                report["rows"].append(row)
                print(json.dumps({key: row[key] for key in (
                    "round", "arm", "elapsed_seconds", "observer_cpu_per_elapsed_second",
                    "missing_owned_fixture_pids", "same_selected_identities_as_first_v1")}), flush=True)
    v2_rows = [row for row in report["rows"] if row["arm"] == "v2_100ms"]
    report["scope_equivalent"] = all(not row["missing_owned_fixture_pids"]
                                     and row["same_selected_identities_as_first_v1"]
                                     for row in report["rows"])
    report["v2_calibration_gate"] = report["scope_equivalent"] and all(
        row["observer_cpu_per_elapsed_second"] <= args.max_observer_ratio
        and not row["sampling"]["stop_timeout"]
        and row["coverage"]["pid_enumeration"].get("full_proc_fallback_samples", 0) == 0
        for row in v2_rows)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return 0 if report["v2_calibration_gate"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=3)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--max-observer-ratio", type=float, default=0.05)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
