"""Stdlib-only, separately pinned outer timing-process measurement.

Added after the quality freeze to close full-process cost accounting. It runs
the unchanged frozen timing child and never changes its policy or measurements.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time


ENVIRONMENT = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def write(path, value):
    with Path(path).open("xb") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True).encode() + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def register(args):
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or not Path(command[0]).is_absolute():
        raise ValueError("Pin an explicit executable and argument vector, without a shell")
    protocol = json.loads(args.protocol.read_text())
    child_sha = digest(args.child_source)
    if child_sha != protocol["source_hashes"].get(args.child_source.name):
        raise ValueError("Timing child source differs from the primary freeze")
    plan = {"schema": "hepta.abc3.temporal-full-timing-process-plan.v1",
            "registration_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "post-quality measurement addition, before timing; primary policy/protocol unchanged",
            "command": command, "command_sha256": hashlib.sha256(canonical(command)).hexdigest(),
            "executable_sha256": digest(command[0]), "cwd": str(Path.cwd()),
            "explicit_environment_overrides": ENVIRONMENT,
            "inherited_environment_recording": "not captured; only the three experiment thread limits are recorded",
            "wrapper_path": str(Path(__file__).resolve()), "wrapper_sha256": digest(__file__),
            "child_source": str(args.child_source.resolve()), "child_source_sha256": child_sha,
            "primary_protocol": str(args.protocol.resolve()), "primary_protocol_sha256": digest(args.protocol),
            "receipt_path": str(args.receipt.resolve())}
    write(args.plan, plan)
    print(json.dumps({"plan_sha256": digest(args.plan), "command_sha256": plan["command_sha256"],
                      "wrapper_sha256": plan["wrapper_sha256"]}))


def run(args):
    plan = json.loads(args.plan.read_text())
    if plan["explicit_environment_overrides"] != ENVIRONMENT:
        raise ValueError("Thread environment differs from the pinned measurement plan")
    for path, expected in ((Path(__file__), plan["wrapper_sha256"]),
                           (plan["child_source"], plan["child_source_sha256"]),
                           (plan["primary_protocol"], plan["primary_protocol_sha256"]),
                           (plan["command"][0], plan["executable_sha256"])):
        if digest(path) != expected:
            raise ValueError("Pinned timing launch input changed")
    if hashlib.sha256(canonical(plan["command"])).hexdigest() != plan["command_sha256"]:
        raise ValueError("Pinned argument vector changed")
    receipt = Path(plan["receipt_path"])
    if receipt.exists():
        raise FileExistsError(receipt)
    environment = dict(os.environ)
    environment.update(ENVIRONMENT)
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    if before.ru_utime or before.ru_stime or before.ru_maxrss:
        raise ValueError("Full-process wrapper must start with no earlier child executions")
    launch_utc = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter_ns()
    child = subprocess.Popen(plan["command"], cwd=plan["cwd"], env=environment)
    exit_code = child.wait()
    wall_ns = time.perf_counter_ns() - started
    exit_utc = datetime.now(timezone.utc).isoformat()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    user_ns = round((after.ru_utime - before.ru_utime) * 1e9)
    system_ns = round((after.ru_stime - before.ru_stime) * 1e9)
    result = {"schema": "hepta.abc3.temporal-full-timing-process-receipt.v1",
              "measurement_plan_sha256": digest(args.plan), "command": plan["command"],
              "command_sha256": plan["command_sha256"], "wrapper_sha256": plan["wrapper_sha256"],
              "child_source_sha256": plan["child_source_sha256"],
              "primary_protocol_sha256": plan["primary_protocol_sha256"],
              "explicit_environment_overrides": ENVIRONMENT, "cwd": plan["cwd"],
              "child_pid": child.pid, "child_exit_code": exit_code,
              "launch_utc": launch_utc, "exit_utc": exit_utc, "full_child_wall_ns": wall_ns,
              "full_child_user_cpu_ns": user_ns, "full_child_system_cpu_ns": system_ns,
              "full_child_cpu_ns": user_ns + system_ns,
              "child_peak_rss_kib": after.ru_maxrss if sys.platform.startswith("linux") else None,
              "peak_rss_scope": "OS RUSAGE_CHILDREN maximum individual child RSS; not sum of concurrent process-tree resident sets",
              "cpu_scope": "OS user+system resource use of the completed child, including its native threads",
              "includes": ["subprocess launch/exec", "Python startup and imports", "CLI and frozen-input validation",
                           "model/policy loading", "all registered sequential timing executions",
                           "per-execution measurement receipts", "final timing-report serialization", "normal child interpreter exit"],
              "excludes": ["outer wrapper Python startup and preparation", "outer receipt serialization",
                           "separate primary quality matrix", "independent post-audit and any required rescores",
                           "actual audio-device playback", "other processes on the shared host"],
              "platform": platform.platform(), "outer_python": sys.version,
              "primary_quality_or_policy_changed": False}
    write(receipt, result)
    print(json.dumps({key: result[key] for key in ("child_exit_code", "full_child_wall_ns", "full_child_cpu_ns", "child_peak_rss_kib")}))
    if exit_code:
        raise SystemExit(exit_code if exit_code > 0 else 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    registration = sub.add_parser("register")
    for name in ("plan", "receipt", "protocol", "child-source"):
        registration.add_argument("--" + name, type=Path, required=True)
    registration.add_argument("command", nargs=argparse.REMAINDER)
    execution = sub.add_parser("run")
    execution.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    register(args) if args.operation == "register" else run(args)


if __name__ == "__main__":
    main()
