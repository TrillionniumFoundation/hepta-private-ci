"""Measure the complete replay driver and all waited descendants with wait4."""

import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from loop_common import identity, read, write


if __name__ == "__main__":
    output = HERE / "measurements"
    output.mkdir(exist_ok=True)
    started = time.perf_counter()
    with (output / "driver.log").open("xb") as stream:
        process = subprocess.Popen([sys.executable, "-B", str(HERE / "run_replay.py"), *sys.argv[1:]],
                                   stdout=stream, stderr=subprocess.STDOUT)
        pid, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    run = Path(sys.argv[sys.argv.index("--output") + 1]).resolve()
    result = {"returncode": process.returncode, "pid": pid,
              "wall_seconds": time.perf_counter() - started, "cpu_user_seconds": usage.ru_utime,
              "cpu_system_seconds": usage.ru_stime, "peak_rss_bytes": usage.ru_maxrss * 1024,
              "scope": "whole driver plus waited descendants, including startup and finalization",
              "measurement_source": identity(Path(__file__)), "log": identity(output / "driver.log")}
    if (run / "SUMMARY.json").exists():
        children = read(run / "SUMMARY.json")["child_process_cpu"]
        result["driver_cpu_user_seconds"] = usage.ru_utime - children["user_seconds"]
        result["driver_cpu_system_seconds"] = usage.ru_stime - children["system_seconds"]
    write(output / "FULL_PROCESS.json", result)
    print(result)
    sys.exit(process.returncode)
