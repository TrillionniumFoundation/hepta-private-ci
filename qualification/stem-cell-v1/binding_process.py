"""Run one research phase and retain child startup-to-exit time, logs and status.

This Linux experiment wrapper launches one child, without retries or CI access.
Child CPU includes its descendants. Inner receipts remain nonadditive breakdowns.
"""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a child command is required")
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    if args.receipt.exists() or args.log.exists():
        raise ValueError("existing phase evidence cannot be overwritten")
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started_ns, wall = time.time_ns(), time.perf_counter_ns()
    with args.log.open("x") as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
        status = process.wait()
    ended_ns, elapsed = time.time_ns(), time.perf_counter_ns() - wall
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = dict(schema="hepta.binding.child-process-cost.v1", command=command,
        started_ns=started_ns, ended_ns=ended_ns, wall_ns=elapsed,
        cpu_ns=round(((after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime)) * 1e9),
        child_max_rss_kib=after.ru_maxrss, platform="Linux", exit_code=status,
        log_file=str(args.log.resolve()), log_sha256=hashlib.sha256(args.log.read_bytes()).hexdigest(),
        scope="child_startup_through_exit_including_descendants_and_failed_attempts",
        nested_phase_receipts_additive=False, retry_performed=False, hosted_ci_consulted=False)
    with args.receipt.open("x") as output:
        json.dump(receipt, output, sort_keys=True, indent=2, allow_nan=False)
        output.write("\n")
    print(json.dumps(receipt), flush=True)
    raise SystemExit(status)


if __name__ == "__main__":
    main()
