"""Bounded Linux qualification runner with create-only attempt output."""

import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time


def main(output):
    output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parent
    files = [source/name for name in ("differentiable.py", "reference_timevarying.py",
                                      "study_timevarying.py", "run_timevarying.py")]
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    request = {"identity": output.name, "source_sha256": before,
               "child_cpu_seconds": [90, 95], "wall_seconds": 150,
               "address_space_bytes": 4*1024**3, "cpu_affinity": [6],
               "full_field_tolerance": 3e-9, "ode_refinement_tolerance": 3e-10,
               "gradient_tolerance": 3e-7, "cold_tolerance": 3e-11,
               "scalar_tolerance": 2e-12, "balance_tolerance": 2e-11,
               "model_training_calls": 0, "old_gates_changed": False,
               "python_executable": sys.executable,
               "python_executable_sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
               "started_unix_seconds": time.time()}
    (output/"REQUEST.json").write_text(json.dumps(request, indent=2)+"\n")
    if 6 not in os.sched_getaffinity(0):
        raise RuntimeError("frozen CPU6 unavailable")
    start = time.perf_counter()
    pid = os.fork()
    if not pid:
        os.sched_setaffinity(0, {6})
        resource.setrlimit(resource.RLIMIT_AS, (4*1024**3, 4*1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (90, 95))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        for name, fd in (("stdout", 1), ("stderr", 2)):
            handle = os.open(output/name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            os.dup2(handle, fd)
            os.close(handle)
        os.setsid()
        env = os.environ.copy()
        env.update({key: "1" for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")})
        os.execve(sys.executable, [sys.executable, "-m", "qualification.hcsn_currentstate.study_timevarying",
                                  str(output)], env)
    killed = False
    while True:
        observed, status, usage = os.wait4(pid, os.WNOHANG)
        if observed:
            break
        if time.perf_counter()-start > 150 and not killed:
            os.killpg(pid, signal.SIGKILL)
            killed = True
        time.sleep(.05)
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    result = {"exit_code": os.waitstatus_to_exitcode(status), "deadline_killed": killed,
              "full_child_wall_seconds": time.perf_counter()-start,
              "full_child_cpu_seconds": usage.ru_utime+usage.ru_stime,
              "full_child_peak_rss_kib": usage.ru_maxrss,
              "source_unchanged": before == after, "source_sha256_after": after}
    (output/"COST.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result), flush=True)
    return 0 if result["exit_code"] == 0 and before == after else 1


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]).resolve()))
