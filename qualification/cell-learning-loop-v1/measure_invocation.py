"""Linux wait4 envelope includes driver startup, exit and all waited children."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

from loop_common import identity, read, write


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    parser.add_argument("runner_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    if not args.label or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in args.label):
        raise ValueError("Use a simple measurement label")
    output = here / "measurements"
    output.mkdir(exist_ok=True)
    log = output / (args.label + ".log")
    started = time.perf_counter()
    with log.open("xb") as stream:
        process = subprocess.Popen([sys.executable, "-B", str(here / "run_loop.py"), *args.runner_args],
                                   stdout=stream, stderr=subprocess.STDOUT)
        pid, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    run = Path(args.runner_args[args.runner_args.index("--output") + 1]).resolve()
    receipts = [read(path) for path in sorted(run.glob("orchestrator-*.json"))]
    own = next((r for r in reversed(receipts) if r["pid"] == pid), None)
    result = {"pid": pid, "returncode": process.returncode,
              "wall_seconds": time.perf_counter() - started,
              "cpu_user_seconds": usage.ru_utime, "cpu_system_seconds": usage.ru_stime,
              "peak_rss_bytes": usage.ru_maxrss * 1024, "log": identity(log),
              "scope": "Linux wait4: complete driver lifetime plus all waited descendants",
              "driver_cpu_user_seconds": None if own is None else usage.ru_utime - own["all_child_cpu_user_seconds"],
              "driver_cpu_system_seconds": None if own is None else usage.ru_stime - own["all_child_cpu_system_seconds"],
              "measurement_source": identity(Path(__file__))}
    write(output / (args.label + ".json"), result)
    print(result)
    sys.exit(process.returncode)
