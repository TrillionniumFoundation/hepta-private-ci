"""Bounded one-attempt precision diagnostic launcher."""

import json
import os
from pathlib import Path
import resource
import signal
import time


HERE = Path(__file__).resolve().parent


def main():
    output = HERE / "attempt001"
    output.mkdir(exist_ok=False)
    python = "/workspace/scratch/d741f7769aeb/hcsn-venv/bin/python"
    command = [python, str(HERE / "diagnose.py"), str(output)]
    started = time.perf_counter()
    pid = os.fork()
    if not pid:
        os.sched_setaffinity(0, {7})
        resource.setrlimit(resource.RLIMIT_AS, (2**32, 2**32))
        resource.setrlimit(resource.RLIMIT_CPU, (120, 125))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        for name, fd in (("stdout", 1), ("stderr", 2)):
            handle = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            os.dup2(handle, fd)
            os.close(handle)
        environment = os.environ.copy()
        environment.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
        os.execve(python, command, environment)
    killed = False
    while True:
        observed, status, usage = os.wait4(pid, os.WNOHANG)
        if observed:
            break
        if time.perf_counter() - started > 150 and not killed:
            os.kill(pid, signal.SIGKILL)
            killed = True
        time.sleep(.05)
    record = {"exit_code": os.waitstatus_to_exitcode(status), "wall_seconds": time.perf_counter()-started,
              "user_seconds": usage.ru_utime, "system_seconds": usage.ru_stime,
              "peak_rss_kib": usage.ru_maxrss, "deadline_kill_sent": killed,
              "cpu_affinity": [7], "address_space_bytes": 2**32, "command": command}
    (output / "COST.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record))


if __name__ == "__main__":
    main()
