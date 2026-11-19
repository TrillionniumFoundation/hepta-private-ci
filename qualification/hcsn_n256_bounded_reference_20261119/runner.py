"""One admitted reference child; CPU limits are set before its interpreter."""

import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time


HERE = Path(__file__).resolve().parent


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    started, cpu = time.perf_counter(), time.process_time()
    request = json.loads((HERE/"REQUEST.json").read_text())
    freeze = json.loads((HERE/"SOURCE_FREEZE.json").read_text())
    if 7 not in os.sched_getaffinity(0):
        raise RuntimeError("CPU7 not available")
    if request["identity"] != "hcsn-n256-bounded-reference-20261119-2f215-attempt001":
        raise ValueError("unique reference identity")
    output = HERE/"evidence/attempt001"
    output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, str(HERE/"study.py"), str(output)]
    write(output/"PROCESS_REQUEST.json", {"command": command, "request": request,
        "source_freeze_sha256": hashlib.sha256((HERE/"SOURCE_FREEZE.json").read_bytes()).hexdigest(),
        "observed_allowed_cpus": sorted(os.sched_getaffinity(0)), "started_unix_seconds": time.time()})
    pid = os.fork()
    if not pid:
        os.sched_setaffinity(0, {7})
        resource.setrlimit(resource.RLIMIT_AS, (2**32, 2**32))
        resource.setrlimit(resource.RLIMIT_CPU, (590, 595))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        for filename, fd in (("stdout", 1), ("stderr", 2)):
            handle = os.open(output/filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            os.dup2(handle, fd)
            os.close(handle)
        environment = os.environ.copy()
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
            environment[name] = "1"
        os.execve(sys.executable, command, environment)
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    killed = False
    while True:
        observed, status, usage = os.wait4(pid, os.WNOHANG)
        if observed:
            break
        if time.perf_counter()-started > 650 and not killed:
            os.kill(pid, signal.SIGKILL)
            killed = True
        time.sleep(.05)
    code = os.waitstatus_to_exitcode(status)
    child_wall = time.perf_counter()-started
    sizes = {str(p.relative_to(output)): p.stat().st_size for p in output.rglob("*") if p.is_file()}
    write(output/"COST.json", {"exit_code": code, "deadline_kill_sent": killed,
        "whole_child_wall_upper_seconds": child_wall, "child_cpu_user_seconds": usage.ru_utime,
        "child_cpu_system_seconds": usage.ru_stime, "child_cpu_seconds": usage.ru_utime+usage.ru_stime,
        "child_maxrss_kib": usage.ru_maxrss, "parent_cpu_seconds_before_final_write": time.process_time()-cpu,
        "controller_interval_before_final_write_seconds": time.perf_counter()-started,
        "artifact_files_before_cost": sizes, "artifact_bytes_before_cost": sum(sizes.values()),
        "full_child_scope": "Includes interpreter imports, source/input checks, independent assembly, all reference work, writing and shutdown; wall upper also includes parent preparation before fork and wait4 polling.",
        "body_cost_separate": True, "numerical_retry": False, "cpu_affinity": [7], "all_closed": False})
    print(json.dumps({"exit_code": code, "deadline_kill_sent": killed, "output": str(output),
                      "child_cpu_seconds": usage.ru_utime+usage.ru_stime, "child_peak_rss_kib": usage.ru_maxrss}), flush=True)
    return code if code >= 0 else 128-code


if __name__ == "__main__":
    raise SystemExit(main())
