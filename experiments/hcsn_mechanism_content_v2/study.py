"""Create-only Linux worker accounting for the four-track research study.

The measured boundary is a fresh interpreter process, including imports,
loading, training, selection, evaluation and serialization. Raw media decoding
is not repeated by these workers; its historical receipt is a separate cost.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import time


THREAD_ENV = {
    "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def check_frozen(root, entries):
    mismatches = [entry["path"] for entry in entries
                  if not (root / entry["path"]).is_file()
                  or digest(root / entry["path"]) != entry["sha256"]]
    if mismatches:
        raise RuntimeError(f"frozen source/input changed: {mismatches}")


def run(plan_path, output, jobs=2):
    if platform.system() != "Linux" or not hasattr(os, "wait4"):
        raise RuntimeError("This cost study requires Linux wait4 resource accounting")
    if not 1 <= jobs <= 2:
        raise ValueError("The frozen host budget permits one or two workers")
    plan_path, output = Path(plan_path).resolve(), Path(output).resolve()
    plan = json.loads(plan_path.read_text())
    root = Path(plan["repository_root"]).resolve()
    check_frozen(root, plan["frozen_files"])
    pending = list(plan["jobs"])
    ids = [job["id"] for job in pending]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate job IDs")
    if any(dep not in ids for job in pending for dep in job.get("depends", [])):
        raise ValueError("dependency is missing from the plan")
    output.mkdir(parents=True, exist_ok=False)
    with (output / "plan.json").open("xb") as stream:
        stream.write(plan_path.read_bytes())
    plan_hash = digest(plan_path)
    start_wall, start_cpu, started = time.perf_counter(), time.process_time(), utc()
    save_new(output / "start.json", {
        "schema": "hcsn-fourtrack-supervisor-start.v1", "started_utc": started,
        "plan_sha256": plan_hash, "max_parallel_workers": jobs,
        "host": platform.platform(), "cpu_count": os.cpu_count(),
        "thread_environment": THREAD_ENV, "direct_energy_joules": None,
        "cost_scope": "complete child interpreter; excludes raw-media decoding",
    })
    active, finished = {}, {}
    while pending or active:
        for job in list(pending):
            if len(active) >= jobs:
                break
            dependencies = job.get("depends", [])
            if not all(dep in finished for dep in dependencies):
                continue
            pending.remove(job)
            receipt_dir = output / "receipts" / job["id"]
            receipt_dir.mkdir(parents=True, exist_ok=False)
            if any(finished[dep]["exit_code"] != 0 for dep in dependencies):
                receipt = {"job_id": job["id"], "exit_code": 125,
                           "executed": False, "reason": "dependency failed"}
                save_new(receipt_dir / "whole_process.json", receipt)
                finished[job["id"]] = receipt
                continue
            try:
                check_frozen(root, plan["frozen_files"])
            except RuntimeError as error:
                receipt = {"job_id": job["id"], "exit_code": 124,
                           "executed": False, "reason": str(error)}
                save_new(receipt_dir / "whole_process.json", receipt)
                finished[job["id"]] = receipt
                continue
            argv = job["argv"]
            if not isinstance(argv, list) or not all(isinstance(s, str) for s in argv):
                raise TypeError("argv must be an explicit string list, never a shell command")
            stdout = (receipt_dir / "stdout.log").open("xb")
            stderr = (receipt_dir / "stderr.log").open("xb")
            env = dict(os.environ)
            env.update(THREAD_ENV)
            begin = {"job_id": job["id"], "argv": argv, "started_utc": utc(),
                     "plan_sha256": plan_hash, "thread_environment": THREAD_ENV,
                     "cwd": str(root), "depends": dependencies}
            save_new(receipt_dir / "start.json", begin)
            wall = time.perf_counter()
            try:
                process = subprocess.Popen(argv, cwd=root, env=env,
                                           stdout=stdout, stderr=stderr)
            except OSError as error:
                stdout.close(); stderr.close()
                receipt = {**begin, "executed": False, "exit_code": 127,
                           "error": str(error), "wall_sec": time.perf_counter() - wall}
                save_new(receipt_dir / "whole_process.json", receipt)
                finished[job["id"]] = receipt
                continue
            active[process.pid] = (process, job, begin, wall, stdout, stderr, receipt_dir)
            print(json.dumps({"event": "start", "job_id": job["id"], "pid": process.pid}), flush=True)
        for pid, entry in list(active.items()):
            process, job, begin, wall, stdout, stderr, receipt_dir = entry
            child, status, usage = os.wait4(pid, os.WNOHANG)
            if not child:
                continue
            process.returncode = os.waitstatus_to_exitcode(status)
            stdout.close(); stderr.close()
            missing = [path for path in job.get("outputs", []) if not (root / path).is_file()]
            frozen_error = None
            try:
                check_frozen(root, plan["frozen_files"])
            except RuntimeError as error:
                frozen_error = str(error)
            evidence_exit = process.returncode or (124 if frozen_error else 123 if missing else 0)
            receipt = {
                **begin, "schema": "hcsn-fourtrack-whole-process.v1", "executed": True,
                "ended_utc": utc(), "exit_code": evidence_exit,
                "process_exit_code": process.returncode,
                "missing_outputs": missing, "frozen_source_error": frozen_error,
                "wall_sec": time.perf_counter() - wall,
                "cpu_user_sec": usage.ru_utime, "cpu_system_sec": usage.ru_stime,
                "cpu_total_sec": usage.ru_utime + usage.ru_stime,
                "peak_rss_kib": usage.ru_maxrss,
                "minor_faults": usage.ru_minflt, "major_faults": usage.ru_majflt,
                "block_input_operations": usage.ru_inblock,
                "block_output_operations": usage.ru_oublock,
                "block_operations_are_bytes": False,
                "direct_energy_joules": None, "gpu_used": False,
                "network_sensor_latency_measured": False,
                "outputs": [{"path": path, "sha256": digest(root / path),
                             "bytes": (root / path).stat().st_size}
                            for path in job.get("outputs", []) if (root / path).is_file()],
                "stdout_sha256": digest(receipt_dir / "stdout.log"),
                "stderr_sha256": digest(receipt_dir / "stderr.log"),
            }
            save_new(receipt_dir / "whole_process.json", receipt)
            finished[job["id"]] = receipt
            del active[pid]
            print(json.dumps({"event": "end", "job_id": job["id"],
                              "exit_code": evidence_exit,
                              "cpu_sec": receipt["cpu_total_sec"]}), flush=True)
        if pending and not active and not any(
                all(dep in finished for dep in job.get("depends", [])) for job in pending):
            raise RuntimeError("cyclic or unsatisfied dependency graph")
        if active:
            time.sleep(0.1)
    result = {
        "schema": "hcsn-fourtrack-supervisor-result.v1", "started_utc": started,
        "ended_utc": utc(), "plan_sha256": plan_hash,
        "jobs": len(finished), "failures": [k for k, v in finished.items() if v["exit_code"]],
        "wall_sec": time.perf_counter() - start_wall,
        "supervisor_cpu_sec": time.process_time() - start_cpu,
        "child_cpu_sec": sum(v.get("cpu_total_sec", 0) for v in finished.values()),
        "max_worker_rss_kib": max((v.get("peak_rss_kib", 0) for v in finished.values()), default=0),
        "max_worker_rss_is_not_concurrent_process_memory": True,
        "direct_energy_joules": None,
    }
    save_new(output / "summary.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    result = run(args.plan, args.output, args.jobs)
    print(json.dumps(result, indent=2))
    raise SystemExit(bool(result["failures"]))
