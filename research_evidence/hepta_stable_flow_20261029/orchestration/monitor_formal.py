"""Read-only training progress and shared-resource snapshots; no quality scores."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--guard-seconds", type=float, default=0.0)
    args = parser.parse_args()
    root = args.output.resolve()
    if not 0 <= args.guard_seconds <= 45:
        raise ValueError("A monitoring wait must be between 0 and 45 seconds")
    deadline = time.monotonic() + args.guard_seconds
    lowest_free = shutil.disk_usage(root).free
    while True:
        current_free = shutil.disk_usage(root).free
        lowest_free = min(lowest_free, current_free)
        if current_free < 8 * 1024 * 1024:
            print(json.dumps({"status": "disk_below_8mib", "disk_available_bytes": current_free,
                              "snapshot_write_skipped": True}), flush=True)
            return
        if time.monotonic() >= deadline:
            break
        time.sleep(max(0.0, min(1.0, deadline - time.monotonic())))
    event_path = sorted((root / "orchestration").glob("session_*/events.jsonl"))[-1]
    events = [json.loads(line) for line in event_path.read_text().splitlines()]
    completed = {e["candidate"]: e for e in events if e["event"] == "candidate_complete"}
    failed = {e["candidate"]: e for e in events
              if e["event"] in ("candidate_failed", "candidate_receipt_failed", "worker_exception")}
    started = {e["candidate"]: e for e in events if e["event"] == "candidate_started"}
    active = []
    for name, event in started.items():
        if name in completed or name in failed:
            continue
        path = root / "candidates" / name / "training_trace.jsonl"
        row = {}
        if path.exists():
            lines = path.read_text().splitlines()
            if lines:
                try:
                    row = json.loads(lines[-1])
                except json.JSONDecodeError:
                    row = json.loads(lines[-2]) if len(lines) > 1 else {}
        active.append({"candidate": name, "pid_in_training_namespace": event["pid"],
                       "update": row.get("update", 0),
                       "training_cpu_seconds": row.get("training_cpu_seconds", 0.0)})
    resources = [{key: e[key] for key in ("candidate", "child_total_cpu_seconds",
                                          "external_wall_seconds", "peak_rss_bytes")}
                 for e in completed.values()]
    cgroup = Path("/sys/fs/cgroup")
    record = {
        "unix_time": time.time(), "session": event_path.parent.name,
        "completed": len(completed), "scientific_failures": len(failed), "active": active,
        "training_cpu_seconds_observed": (
            sum(e["verification"]["training_cpu_seconds"] for e in completed.values())
            + sum(e["training_cpu_seconds"] for e in active)),
        "completed_full_child_cpu_seconds": sum(e["child_total_cpu_seconds"] for e in resources),
        "completed_peak_rss_bytes_max": max((e["peak_rss_bytes"] for e in resources), default=0),
        "last_completed_resources": resources[-4:],
        "selection_exists": (root / "selection.json").exists(),
        "primary_test_results_exist": (root / "results.json").exists(),
        "shared_cgroup_memory_current_bytes": int((cgroup / "memory.current").read_text()),
        "shared_cgroup_memory_peak_bytes": int((cgroup / "memory.peak").read_text()),
        "shared_cgroup_memory_events": (cgroup / "memory.events").read_text().strip(),
        "shared_cgroup_cpu_stat": (cgroup / "cpu.stat").read_text().strip(),
        "disk_available_bytes": shutil.disk_usage(root).free,
        "guard_lowest_available_bytes": lowest_free,
        "formal_evidence_file_bytes": sum(path.stat().st_size for path in root.rglob("*") if path.is_file()),
        "whole_oct29_evidence_file_bytes": sum(path.stat().st_size for path in root.parent.rglob("*") if path.is_file()),
        "resource_scope": "wait4 is per completed child; cgroup values cover shared managed work and cannot be attributed solely to this study",
        "validation_or_test_content_read": False,
    }
    folder = root / "orchestration" / "monitor_snapshots"
    folder.mkdir(exist_ok=True)
    path = folder / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ") + ".json")
    with path.open("x") as stream:
        json.dump(record, stream, indent=2, sort_keys=True, allow_nan=False)
    print(json.dumps({key: record[key] for key in (
        "completed", "scientific_failures", "active", "training_cpu_seconds_observed",
        "completed_full_child_cpu_seconds", "completed_peak_rss_bytes_max",
        "shared_cgroup_memory_current_bytes", "shared_cgroup_memory_events",
        "disk_available_bytes", "formal_evidence_file_bytes", "whole_oct29_evidence_file_bytes",
        "selection_exists", "primary_test_results_exist")}, indent=2))


if __name__ == "__main__":
    main()
