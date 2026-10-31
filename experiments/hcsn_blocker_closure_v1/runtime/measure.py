"""Launch a whole runtime worker and retain non-overlapping CPU scopes."""

import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, "-m", __package__ + ".task_runtime",
               "--output", str(args.output), "--binary", str(args.binary)]
    if args.preflight:
        command.append("--preflight")
    outer_cpu, started = time.process_time(), time.perf_counter()
    with (args.output / "WORKER.log").open("wb") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    receipt = {
        "schema": "hcsn-task-runtime-whole-worker-cost.v1",
        "command": command,
        "exit_code": process.returncode,
        "wall_seconds": time.perf_counter()-started,
        "worker_and_reaped_descendant_cpu_seconds": usage.ru_utime+usage.ru_stime,
        "launcher_cpu_seconds_from_before_spawn": time.process_time()-outer_cpu,
        "worker_peak_rss_kib": usage.ru_maxrss,
        "cost_scope": "Exact worker PID wait4; includes Python imports, oracle solve, model initialization, all native children, IPC, persistence, evidence writing, and checks. Excludes this launcher's imports and installation.",
        "nested_warning": "Native child CPU and worker self CPU are components of the wait4 total; do not add them to it.",
        "rss_scope": "Linux wait4 maximum RSS is a peak statistic, not the sum of concurrent processes or memory traffic.",
        "hardware_energy_joules": None,
        "training_performed": False,
        "production_authority": False,
    }
    (args.output / "WHOLE_WORKER_COST.json").write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    print(json.dumps(receipt, sort_keys=True), flush=True)
    raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
