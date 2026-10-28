#!/usr/bin/env python3
"""Owned-tree read-cost diagnosis and predeclared 300/500 ms cadence calibration."""
import json
import os
from pathlib import Path
import time
from collections import defaultdict
from calibrate_process_metrics_v2 import own_cgroup, live_process, TREE, BRANCH, identities
from process_metrics import CgroupScope, ProcessMetrics as V1
from process_metrics_v2 import ProcessMetrics as V2

def main():
    output = Path("evidence/metrics-v2-cadence-calibration-r2.json")
    if output.exists():
        raise RuntimeError("output already exists")
    if int(Path("/proc/self/stat").read_text().split("(", 1)[0]) != os.getpid():
        raise RuntimeError("proc PID namespace differs")
    report = {"schema": "hepta.metrics.cadence-calibration.v1",
              "predeclared_intervals_seconds": [0.3, 0.5], "seconds_per_arm": 3,
              "rounds": 2, "max_observer_ratio": 0.05,
              "formal_interval_candidate_seconds": 0.5,
              "reason": "100ms candidate failed 5% gate; retain fresh PSS, full selected scopes and both identity reads",
              "rows": [], "read_cost_diagnostic": {}}
    group = own_cgroup()
    with live_process(TREE) as (_, tree), live_process(BRANCH) as (_, extra):
        expected = {os.getpid(), tree["root"], *tree["descendants"], extra["root"], *extra["descendants"]}
        def collector(cls, interval):
            return cls(root_pids=[os.getpid()], extra_pids=[extra["root"]],
                       cgroup_paths=[CgroupScope(group)] if group else [], sample_interval=interval)
        baseline = collector(V1, 0.1).start()
        time.sleep(0.3)
        baseline_metrics = baseline.stop()
        reference = identities(baseline_metrics)
        report["reference_identities"] = sorted(reference)
        report["reference_metrics"] = baseline_metrics
        counters = defaultdict(lambda: {"calls": 0, "cpu_seconds": 0.0, "wall_seconds": 0.0})
        original = Path.read_text
        def diagnosed(path, *args, **kwargs):
            name = path.name if path.name in {"stat", "smaps_rollup", "children", "cgroup.procs", "cpu.stat", "memory.current", "memory.peak"} else "other"
            cpu, wall = time.thread_time(), time.monotonic()
            try:
                return original(path, *args, **kwargs)
            finally:
                row = counters[name]; row["calls"] += 1
                row["cpu_seconds"] += time.thread_time() - cpu
                row["wall_seconds"] += time.monotonic() - wall
        Path.read_text = diagnosed
        try:
            measured = collector(V2, 0.1).start()
            time.sleep(3)
            diagnostic = measured.stop()
        finally:
            Path.read_text = original
        report["read_cost_diagnostic"] = {"includes_diagnostic_wrapper_overhead": True, "not_a_formal_performance_result": True,
                                           "categories": dict(counters), "metrics": diagnostic}
        for round_index in range(2):
            intervals = [0.3, 0.5] if round_index == 0 else [0.5, 0.3]
            for interval in intervals:
                measured = collector(V2, interval).start()
                time.sleep(3)
                metrics = measured.stop()
                observed = identities(metrics)
                row = {"round": round_index, "interval_seconds": interval,
                       "observer_cpu_ratio": metrics["sampling"]["observer_cpu_seconds"] / metrics["elapsed_seconds"],
                       "same_scope": observed == reference,
                       "missing_expected_pids": sorted(expected - {p["pid"] for p in metrics["processes"]}),
                       "missing_vs_reference": sorted(reference - observed),
                       "added_vs_reference": sorted(observed - reference), "metrics": metrics}
                report["rows"].append(row)
                print(json.dumps({k: v for k, v in row.items() if k != "metrics"}), flush=True)
    with output.with_suffix(".raw.json").open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    selected = [row for row in report["rows"] if row["interval_seconds"] == 0.5]
    report["formal_500ms_gate"] = all(row["same_scope"] and not row["missing_expected_pids"]
        and row["observer_cpu_ratio"] <= 0.05
        and not row["metrics"]["sampling"]["stop_timeout"]
        and not row["metrics"]["coverage"]["gaps"]
        and row["metrics"]["coverage"]["pid_enumeration"].get("full_proc_fallback_samples", 0) == 0
        for row in selected)
    report["limits"] = ["Stable owned-tree scope parity does not prove dynamic fork/exit completeness.",
                        "500ms after each sample misses more short peaks; PSS remains fresh simultaneous selected-scope sampled lower bounds.",
                        "No cached PSS, RSS substitution, omitted selected PID, or uncounted observer thread is used.",
                        "The formal lane must report actual observer ratio and gaps independently."]
    with output.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print("FORMAL_500MS_CALIBRATION_GATE", report["formal_500ms_gate"], flush=True)
    return 0 if report["formal_500ms_gate"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
