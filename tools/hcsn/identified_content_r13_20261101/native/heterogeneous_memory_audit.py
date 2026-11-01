"""Correct /proc PID-namespace mapping for the independent-Q memory witness.

The original CPU/quality run is retained unchanged. This program reuses exactly
its numerical worker, patches only its RSS reader, and gives the parent the
worker's outer /proc PID before importing numerical dependencies.
"""

import argparse
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time

import heterogeneous_cells as experiment

ROOT = Path(__file__).resolve().parent


def process_status(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        name, value = line.split(":", 1)
        if name in ["Name", "Pid", "Tgid", "NSpid", "VmRSS", "VmHWM"]:
            values[name] = value.strip()
    return values


def own_rss(pid):
    if pid != os.getpid():
        raise ValueError("Worker RSS reader requires this process")
    return int(process_status("/proc/self/status")["VmRSS"].split()[0]) * 1024


def worker(method, start, count, pid_receipt):
    status = process_status("/proc/self/status")
    identity = {"namespace_pid": os.getpid(), "proc_mount_pid": int(status["Pid"]),
        "NSpid": list(map(int, status["NSpid"].split())), "status": status,
        "memory_audit_source_sha256": experiment.sha(__file__)}
    Path(pid_receipt).write_text(json.dumps(identity) + "\n")
    experiment.rss = own_rss
    result = experiment.worker(method, start, count)
    result["proc_pid_identity"] = identity
    result["memory_audit_source_sha256"] = experiment.sha(__file__)
    return result


def group(destination, count, method, environment):
    shards = [(0, count)] if count <= 128 else [(0, 128), (128, 128)]
    pending, receipts, peak, samples = {}, [], 0, []
    start_time = time.perf_counter()
    label = f"cells{count}_{method}"
    for index, (start, size) in enumerate(shards):
        stem = destination/f"{label}_worker{index}"
        stdout, stderr = stem.with_suffix(".json").open("x"), stem.with_suffix(".stderr").open("x")
        pid_path = stem.with_suffix(".pid.json")
        command = [sys.executable, str(Path(__file__).resolve()), "--worker", method,
                   "--start", str(start), "--count", str(size), "--pid-receipt", str(pid_path)]
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=environment)
        pending[process.pid] = {"process": process, "stdout": stdout, "stderr": stderr,
            "stem": stem, "pid_path": pid_path, "identity": None, "command": command}
    while pending:
        total, observed = 0, 0
        for pid, item in pending.items():
            if item["identity"] is None and item["pid_path"].exists():
                try:
                    item["identity"] = json.loads(item["pid_path"].read_text())
                except json.JSONDecodeError:
                    continue
            if item["identity"] is not None:
                identity = item["identity"]
                if identity["namespace_pid"] != pid:
                    raise AssertionError("Child PID handshake mismatch")
                try:
                    status = process_status(f"/proc/{identity['proc_mount_pid']}/status")
                    if int(status["NSpid"].split()[-1]) != pid:
                        raise AssertionError("/proc PID reuse or namespace mismatch")
                    if "VmRSS" in status:
                        total += int(status["VmRSS"].split()[0]) * 1024
                        observed += 1
                except FileNotFoundError:
                    pass
        peak = max(peak, total)
        samples.append([time.perf_counter() - start_time, total, observed])
        for pid in list(pending):
            done, status, usage = os.wait4(pid, os.WNOHANG)
            if done:
                item = pending.pop(pid)
                item["process"].returncode = os.waitstatus_to_exitcode(status)
                item["stdout"].close(); item["stderr"].close()
                receipts.append({"pid": pid, "returncode": item["process"].returncode,
                    "whole_child_cpu_seconds": usage.ru_utime + usage.ru_stime,
                    "whole_child_peak_rss_bytes": usage.ru_maxrss * 1024,
                    "proc_pid_identity": item["identity"], "command": item["command"],
                    "stdout": item["stem"].with_suffix(".json").name,
                    "stderr": item["stem"].with_suffix(".stderr").name})
        if pending:
            time.sleep(.005)
    process_receipt = {"workers": receipts, "rss_samples": samples,
        "sampled_peak_sum_worker_rss_bytes": peak,
        "sum_individual_whole_child_peak_rss_upper_bound_bytes": sum(x["whole_child_peak_rss_bytes"] for x in receipts)}
    (destination/f"{label}_PROCESS_RECEIPT.json").write_text(json.dumps(process_receipt, indent=2) + "\n")
    if any(x["returncode"] != 0 for x in receipts):
        raise AssertionError(process_receipt)
    rows = [json.loads((destination/x["stdout"]).read_text()) for x in receipts]
    rows.sort(key=lambda row: row["start_index"])
    return {"count": count, "method": method, "worker_count": len(rows),
        **{key: sum(x[key] for x in rows) for key in ["baseline_rss_after_imports_bytes",
            "execution_current_rss_bytes", "execution_peak_rss_bytes", "cache_payload_bytes",
            "planner_array_logical_bytes", "unique_transition_payload_bytes"]},
        "sampled_peak_sum_worker_rss_bytes": peak,
        "sum_individual_whole_child_peak_rss_upper_bound_bytes": process_receipt["sum_individual_whole_child_peak_rss_upper_bound_bytes"],
        "worker_input_sha256": [x["input_sha256"] for x in rows],
        "maximum_posterior_error": max(x["maximum_posterior_error"] for x in rows),
        "quality_pass": all(x["quality_pass"] for x in rows),
        "own_RSS_positive": all(x["baseline_rss_after_imports_bytes"] > 0 and x["execution_current_rss_bytes"] > 0 for x in rows),
        "sampled_RSS_positive": peak > 0}


def run(destination):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    original = ROOT/"evidence/heterogeneous_cells/RESULTS.json"
    original_result = json.loads(original.read_text())
    invalid = {"schema": "hcsn-r13-heterogeneous-memory-correction-v1", "original_results_sha256": experiment.sha(original),
        "original_numerical_program_sha256": experiment.sha(ROOT/"heterogeneous_cells.py"),
        "memory_audit_source_sha256": experiment.sha(__file__),
        "original_cpu_repetitions_retained": True, "rerun_scope": "one memory repetition per cell-count/backend, with identical numerical worker",
        "invalid_original_fields": ["baseline_rss_after_imports_bytes", "execution_current_rss_bytes", "sampled_peak_sum_worker_rss_bytes"],
        "reason": "os.getpid reports the inner PID namespace; mounted /proc/PID addresses the outer namespace. The original reader could return zero or another process. resource.getrusage ru_maxrss and wait4 rusage do not use that path and remain valid.",
        "replacement": "Worker reads /proc/self/status; parent receives outer Pid/NSpid handshake and checks it before sampling.",
        "self_status": process_status("/proc/self/status"), "namespace_pid": os.getpid(),
        "memory_before": experiment.memory_snapshot()}
    (destination/"PLAN.json").write_text(json.dumps(invalid, indent=2) + "\n")
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", OPENBLAS_NUM_THREADS="1",
                       OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    jobs = [(n, method) for n in [1, 16, 64, 256] for method in ["native", "numpy_cached"]]
    random.Random(20261101257).shuffle(jobs)
    rows = []
    for index, (count, method) in enumerate(jobs):
        row = group(destination, count, method, environment)
        expected = next(g for g in original_result["results"] if g["count"] == count and g["method"] == method)
        row["same_inputs_as_original"] = row["worker_input_sha256"] == expected["worker_input_sha256"]
        rows.append(row)
        print(json.dumps({"completed": index + 1, "total": len(jobs), "cells": count, "method": method,
            "sampled_peak_RSS_MiB": row["sampled_peak_sum_worker_rss_bytes"] / 1024**2}), flush=True)
    mismatch = experiment.freeze_matches()
    report = {"schema": "hcsn-r13-heterogeneous-memory-corrected-v1", "correction": invalid,
        "results": rows, "frozen_source_mismatches": mismatch,
        "all_passed": not mismatch and all(x["quality_pass"] and x["own_RSS_positive"] and
            x["sampled_RSS_positive"] and x["same_inputs_as_original"] for x in rows),
        "memory_after": experiment.memory_snapshot(),
        "scope": "RSS sums double count shared resident pages. 5ms sampled simultaneous peaks include post-timing numerical verification; execution snapshots and kernel high-water values are also retained. Multi-worker sums of individual high-water marks are upper bounds, not an exact simultaneous peak. These one-repetition memory runs do not replace the original three-repetition CPU medians."}
    (destination/"RESULTS.json").write_text(json.dumps(report, indent=2) + "\n")
    if not report["all_passed"]:
        raise AssertionError(report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT/"evidence/heterogeneous_cells/memory_corrected")
    parser.add_argument("--worker", choices=["native", "numpy_cached"])
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--pid-receipt", type=Path)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.worker, args.start, args.count, args.pid_receipt)))
    else:
        run(args.output)
