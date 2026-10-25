"""Exact-PID complete phase cost, including startup, imports and normal exit."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


THREADS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("xb") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True).encode() + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    prepare = sub.add_parser("register")
    prepare.add_argument("--plan", type=Path, required=True)
    prepare.add_argument("--receipt", type=Path, required=True)
    prepare.add_argument("--phase", required=True)
    prepare.add_argument("--input", type=Path, action="append", default=[])
    prepare.add_argument("command", nargs=argparse.REMAINDER)
    execute = sub.add_parser("run")
    execute.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    if args.operation == "register":
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not command or not Path(command[0]).is_absolute():
            raise ValueError("Use an absolute executable and explicit argument vector")
        inputs = [Path(__file__).resolve(), Path(command[0]), *args.input]
        plan = {"schema": "hepta.abc4.temporal-process-plan.v1", "phase": args.phase,
                "registered_utc": datetime.now(timezone.utc).isoformat(),
                "command": command, "cwd": str(Path.cwd()), "thread_environment": THREADS,
                "input_sha256": {str(path.resolve()): digest(path) for path in inputs},
                "receipt": str(args.receipt.resolve())}
        write(args.plan, plan)
        print(json.dumps({"plan_sha256": digest(args.plan)}), flush=True)
        return
    plan = json.loads(args.plan.read_text())
    if plan["thread_environment"] != THREADS or Path(plan["receipt"]).exists():
        raise ValueError("Process plan changed or already executed")
    for path, identity in plan["input_sha256"].items():
        if digest(path) != identity:
            raise ValueError("Pinned process input changed")
    environment = dict(os.environ)
    environment.update(THREADS)
    launch = datetime.now(timezone.utc).isoformat()
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    child = subprocess.Popen(plan["command"], cwd=plan["cwd"], env=environment)
    pid, status, usage = os.wait4(child.pid, 0)
    child.returncode = os.waitstatus_to_exitcode(status)
    if pid != child.pid:
        raise RuntimeError("Different child PID was measured")
    result = {"schema": "hepta.abc4.temporal-process-receipt.v1", "phase": plan["phase"],
              "plan_sha256": digest(args.plan), "command": plan["command"],
              "launch_utc": launch, "exit_utc": datetime.now(timezone.utc).isoformat(),
              "child_pid": pid, "exit_code": child.returncode,
              "full_child_wall_ns": time.perf_counter_ns() - wall,
              "full_child_cpu_ns": round((usage.ru_utime + usage.ru_stime) * 1e9),
              "child_peak_rss_kib": usage.ru_maxrss,
              "outer_cpu_ns": time.process_time_ns() - cpu,
              "resource_measurement": "os.wait4 exact new child PID; no cumulative prior-child counters",
              "scope": "launch/imports/input validation/model loads/all phase work/report writes/child exit; excludes outer wrapper startup and receipt serialization; no sum of concurrent resident memory"}
    write(plan["receipt"], result)
    print(json.dumps(result), flush=True)
    if child.returncode:
        raise SystemExit(child.returncode if child.returncode > 0 else 1)


if __name__ == "__main__":
    main()
