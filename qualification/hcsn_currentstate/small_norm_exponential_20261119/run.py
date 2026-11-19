"""Bound two fresh source-frozen verification processes; preserve every result."""

import json
import os
from pathlib import Path
import resource
import signal
import time


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def main():
    root = HERE / "verification001"
    root.mkdir(exist_ok=False)
    python = "/workspace/scratch/d741f7769aeb/hcsn-venv/bin/python"
    rows = []
    roster = (("regression", "qualification.hcsn_currentstate.small_norm_exponential_20261119.verify"),
              ("timevarying", "qualification.hcsn_currentstate.study_timevarying"))
    for label, module in roster:
        output = root / label
        output.mkdir()
        command = [python, "-m", module, str(output)]
        started = time.perf_counter()
        pid = os.fork()
        if not pid:
            os.chdir(REPO)
            os.sched_setaffinity(0, {7})
            resource.setrlimit(resource.RLIMIT_AS, (2**32, 2**32))
            resource.setrlimit(resource.RLIMIT_CPU, (120, 125))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            for name, fd in (("stdout", 1), ("stderr", 2)):
                handle = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                os.dup2(handle, fd)
                os.close(handle)
            env = os.environ.copy()
            env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
            os.execve(python, command, env)
        killed = False
        while True:
            observed, status, usage = os.wait4(pid, os.WNOHANG)
            if observed:
                break
            if time.perf_counter()-started > 150 and not killed:
                os.kill(pid, signal.SIGKILL)
                killed = True
            time.sleep(.05)
        record = {"label": label, "command": command, "exit_code": os.waitstatus_to_exitcode(status),
                  "whole_child_wall_seconds": time.perf_counter()-started,
                  "child_user_seconds": usage.ru_utime, "child_system_seconds": usage.ru_stime,
                  "child_peak_rss_kib": usage.ru_maxrss, "deadline_kill_sent": killed}
        (output / "COST.json").write_text(json.dumps(record, indent=2) + "\n")
        rows.append(record)
        if record["exit_code"]:
            break
    (root / "CONTROLLER.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
