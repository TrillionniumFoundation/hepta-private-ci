"""Meter one bounded audit process and its waited recovery subprocesses."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--stage", choices=("development", "formal"), default="development")
    parser.add_argument("--frozen-commit", default="")
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists():
        parser.error("An attempt directory must not already exist")
    out.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-B", str(Path(__file__).with_name("audit.py")),
               "--out", str(out), "--stage", args.stage,
               "--frozen-commit", args.frozen_commit]
    env = dict(os.environ)
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        env[name] = "1"
    stdout = out.with_suffix(".stdout.log")
    stderr = out.with_suffix(".stderr.log")
    started = datetime.now(timezone.utc).isoformat()
    wall = time.perf_counter()
    with stdout.open("x") as stdout_stream, stderr.open("x") as stderr_stream:
        pid = os.fork()
        if pid == 0:
            os.dup2(stdout_stream.fileno(), 1)
            os.dup2(stderr_stream.fileno(), 2)
            resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
            os.execve(sys.executable, command, env)
        _, status, usage = os.wait4(pid, 0)
    receipt = {
        "schema": "hcsn.r13.age-checkpoint.wait4.v1",
        "command": command,
        "started_utc": started,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "returncode": os.waitstatus_to_exitcode(status),
        "wall_seconds": time.perf_counter() - wall,
        "child_user_cpu_seconds": usage.ru_utime,
        "child_system_cpu_seconds": usage.ru_stime,
        "child_total_cpu_seconds": usage.ru_utime + usage.ru_stime,
        "peak_rss_bytes": usage.ru_maxrss * 1024,
        "limits": {"threads": 1, "address_space_bytes": 512 * 1024**2, "cpu_seconds": 120},
        "scope": "Linux wait4 accounting for the scientific child and its waited fresh-process recovery descendants; includes imports and evidence writes; excludes this launcher and unrelated concurrent work. Peak RSS is the maximum process RSS, not a sum or energy reading.",
        "logs": [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                  "bytes": path.stat().st_size} for path in (stdout, stderr)],
    }
    receipt_path = out / "PROCESS_RECEIPT.json" if out.exists() else out.with_suffix(".PROCESS_RECEIPT.json")
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
    return receipt["returncode"]


if __name__ == "__main__":
    raise SystemExit(main())
