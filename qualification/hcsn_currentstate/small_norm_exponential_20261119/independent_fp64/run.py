"""One create-only bounded child; no relaunch after uncertain termination."""
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time

root = Path(__file__).resolve().parent
plan = json.loads((root / "PLAN.json").read_text())
for name, key in (("kernel_snapshot.py", "kernel_sha256"), ("review.py", "review_sha256")):
    if hashlib.sha256((root / name).read_bytes()).hexdigest() != plan[key]:
        raise ValueError("source mismatch")
output = root / "attempt001"
output.mkdir(exist_ok=False)
started = time.perf_counter()
pid = os.fork()
if pid == 0:
    os.sched_setaffinity(0, plan["cpu_affinity"])
    resource.setrlimit(resource.RLIMIT_AS, (plan["address_space_bytes"],) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, tuple(plan["cpu_seconds"]))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    for name, fd in (("stdout", 1), ("stderr", 2)):
        handle = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        os.dup2(handle, fd)
        os.close(handle)
    os.setsid()
    env = os.environ.copy()
    env.update({name: "1" for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")})
    os.execve(sys.executable, [sys.executable, str(root / "review.py")], env)
killed = False
while True:
    observed, status, usage = os.wait4(pid, os.WNOHANG)
    if observed:
        break
    if time.perf_counter() - started > plan["wall_seconds"] and not killed:
        os.killpg(pid, signal.SIGKILL)
        killed = True
    time.sleep(.05)
after = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
         for name in ("kernel_snapshot.py", "review.py")}
result = {"exit_code": os.waitstatus_to_exitcode(status), "deadline_killed": killed,
          "full_child_wall_seconds": time.perf_counter() - started,
          "full_child_cpu_seconds": usage.ru_utime + usage.ru_stime,
          "full_child_peak_rss_kib": usage.ru_maxrss, "source_sha256_after": after,
          "source_unchanged": after["kernel_snapshot.py"] == plan["kernel_sha256"]
                              and after["review.py"] == plan["review_sha256"]}
(output / "COST.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
raise SystemExit(0 if result["exit_code"] == 0 and result["source_unchanged"] else 1)
