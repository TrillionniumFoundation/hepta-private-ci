"""Meter the complete scientific child, including imports and evidence writes."""

import argparse
import datetime
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[3]
    command = [sys.executable, "-B", "-m", "experiments.hcsn_validation_r14_20261101.numerics.audit", "--out", str(out)]
    environment = dict(os.environ)
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        environment[name] = "1"
    def limits():
        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (600, 600))
    started = time.perf_counter(); utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with (out / "stdout.log").open("x") as stdout, (out / "stderr.log").open("x") as stderr:
        process = subprocess.Popen(command, cwd=root, env=environment, stdout=stdout, stderr=stderr, preexec_fn=limits)
        pid, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    receipt = {"started_utc": utc, "pid": pid, "command": command, "exit_code": process.returncode,
        "wall_seconds": time.perf_counter() - started,
        "user_cpu_seconds": usage.ru_utime, "system_cpu_seconds": usage.ru_stime,
        "full_child_cpu_seconds": usage.ru_utime + usage.ru_stime,
        "peak_process_rss_bytes": usage.ru_maxrss * 1024,
        "memory_limit_bytes": 1024**3, "cpu_limit_seconds": 600, "blas_threads": 1,
        "scope": "Linux wait4 of complete scientific child; includes imports, references, all solver calls and evidence writes. Nested phase times must not be added.",
        "energy_joules": None}
    with (out / "PROCESS_RECEIPT.json").open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
    print(json.dumps(receipt, sort_keys=True)); raise SystemExit(process.returncode)
